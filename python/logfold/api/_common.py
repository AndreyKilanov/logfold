"""Shared helpers of the public facade: option resolution, one mining call and result building."""

from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from logfold._version import get_version
from logfold.config import (
    DEFAULT_CHUNK_BYTES,
    DEFAULT_MASKS,
    HIGH_CARDINALITY_MAX_TEMPLATES,
    ExamplesMode,
    ExecutionConfig,
    MaskRule,
    MiningConfig,
    config_fingerprint,
)
from logfold.engines.base import MineRequest, MiningResult, RunCounters, StateRequest, TemplateTable
from logfold.engines.select import select_engine
from logfold.errors import ConfigError, read_error
from logfold.ext.formats import FormatSpec
from logfold.ext.masks import Masker, validate_masks
from logfold.formats import ResolvedFormat
from logfold.model import (
    SCHEMA_VERSION,
    ResultMeta,
    RunSummary,
    Template,
)
from logfold.timestamps import micros_to_datetimes

logger = logging.getLogger("logfold")

PathLike = str | os.PathLike[str]
Progress = Callable[[int], None]
UNPARSED_WARNING_RATIO = 0.10
ALGO_VERSION = 1


def _paths(value: PathLike | Sequence[PathLike], what: str) -> tuple[str, ...]:
    items: Sequence[PathLike] = [value] if isinstance(value, (str, os.PathLike)) else list(value)
    if not items:
        raise ConfigError(f"{what} needs at least one input")
    return tuple(os.fspath(item) for item in items)


def _mining(
    base: MiningConfig | None,
    depth: int | None,
    sim_th: float | None,
    max_children: int | None,
    max_templates: int | None,
    masks: Sequence[MaskRule] | None,
    high_cardinality: bool = False,
) -> MiningConfig:
    config = base or MiningConfig()
    if high_cardinality and max_templates is None:
        max_templates = min(config.max_templates, HIGH_CARDINALITY_MAX_TEMPLATES)
    changes: dict[str, Any] = {}
    for key, value in (
        ("depth", depth),
        ("sim_th", sim_th),
        ("max_children", max_children),
        ("max_templates", max_templates),
    ):
        if value is not None:
            changes[key] = value
    if masks is not None:
        changes["masks"] = tuple(masks)
    config = dataclasses.replace(config, **changes) if changes else config
    validate_masks(config.masks)
    return config


def _execution(
    base: ExecutionConfig | None,
    engine: str | None,
    strategy: str | None,
    threads: int | None,
    chunk_bytes: int | None,
    high_cardinality: bool = False,
    warm_start: bool | None = None,
) -> ExecutionConfig:
    config = base or ExecutionConfig()
    if high_cardinality and strategy is None and config.strategy == "auto":
        strategy = "sequential"
    changes: dict[str, Any] = {}
    for key, value in (
        ("engine", engine),
        ("strategy", strategy),
        ("threads", threads),
        ("chunk_bytes", chunk_bytes),
        ("warm_start", warm_start),
    ):
        if value is not None:
            changes[key] = value
    return dataclasses.replace(config, **changes) if changes else config


def _total_size(runs: tuple[tuple[str, ...], ...]) -> int:
    total = 0
    for files in runs:
        for path in files:
            if path != "-":
                try:
                    total += os.stat(path).st_size
                except OSError as error:
                    raise read_error(path, error) from error
    return total


STATE_FORMATS = ("json", "binary")


def _state(
    load: PathLike | None,
    save: PathLike | None,
    state_format: str,
    mining: MiningConfig,
    spec: FormatSpec,
) -> StateRequest | None:
    """Build the state request of ``analyze()``, or ``None`` when no state file is involved."""
    if state_format not in STATE_FORMATS:
        raise ConfigError(f"state_format must be one of {', '.join(STATE_FORMATS)}, got {state_format!r}")
    if load is None and save is None:
        return None
    return StateRequest(
        load=None if load is None else os.fspath(load),
        save=None if save is None else os.fspath(save),
        format=state_format,
        config_hash=config_fingerprint(mining),
        masks="default" if mining.masks == DEFAULT_MASKS else "custom",
        logfold_version=get_version(),
        log_format=spec.name,
    )


def _resolve_strategy(execution: ExecutionConfig, runs: tuple[tuple[str, ...], ...]) -> str:
    if execution.strategy != "auto":
        return execution.strategy
    return "adaptive" if _total_size(runs) > execution.chunk_bytes else "sequential"


def _mine(
    runs: tuple[tuple[str, ...], ...],
    spec: FormatSpec,
    mining: MiningConfig,
    execution: ExecutionConfig,
    progress: Progress | None,
    recount: bool = False,
    windows: tuple[tuple[int | None, int | None], ...] = (),
    state: StateRequest | None = None,
    matching: bool = False,
) -> MiningResult:
    engine = select_engine(execution)
    request = MineRequest(
        runs=runs,
        format=spec,
        mining=mining,
        strategy=_resolve_strategy(execution, runs),
        threads=execution.threads,
        chunk_bytes=execution.chunk_bytes,
        warm_start=execution.warm_start,
        recount=recount,
        windows=windows,
        state=state,
    )
    return engine.match(request, progress) if matching else engine.mine(request, progress)


def _summary(paths: tuple[str, ...], info: RunCounters) -> RunSummary:
    return RunSummary(
        name=",".join(paths),
        files=info.files,
        lines=info.lines,
        records=info.records,
        unparsed=info.unparsed,
        bytes=info.bytes,
        tz_aware=info.tz_aware,
        overflowed=info.overflowed,
        out_of_range=info.out_of_range,
        untimed=info.untimed,
    )


def _example(text: str | None, mode: ExamplesMode, masker: Masker) -> str | None:
    if text is None or mode == "none":
        return None
    return masker.mask(text) if mode == "masked" else text


def _templates(
    table: TemplateTable, run: int, tz_aware: bool, mode: ExamplesMode, masker: Masker
) -> tuple[Template, ...]:
    columns = table.runs[run]
    first = micros_to_datetimes(columns.first, tz_aware)
    last = micros_to_datetimes(columns.last, tz_aware)
    examples: Sequence[str | None] = columns.examples
    if mode == "none":
        examples = [None] * len(table)
    elif mode == "masked":
        examples = [None if text is None else masker.mask(text) for text in examples]
    return tuple(
        Template(identifier, text, count, started, ended, sample, level, levels)
        for identifier, text, count, started, ended, sample, level, levels in zip(
            table.ids, table.texts, columns.counts, first, last, examples, columns.level, columns.levels, strict=True
        )
        if count > 0
    )


def _warnings(
    summaries: Sequence[RunSummary],
    execution: ExecutionConfig,
    resolved: ResolvedFormat,
    mining: MiningConfig,
    high_cardinality: bool,
    strategy: str,
) -> list[str]:
    warnings: list[str] = []
    if strategy == "sequential":
        warnings.extend(_ignored_chunk_options(execution, high_cardinality))
    for summary in summaries:
        if summary.lines and summary.unparsed_ratio > UNPARSED_WARNING_RATIO:
            warnings.append(
                f"{summary.unparsed_ratio:.0%} of lines in {summary.name} did not match the format; "
                "check the format or enable multiline"
            )
        if summary.overflowed:
            hint = (
                "high-cardinality mode: records beyond the first templates were pooled into catch-all templates"
                if high_cardinality
                else "consider high_cardinality=True (faster, bounded memory) or a larger max_templates"
            )
            warnings.append(
                f"{summary.name}: max_templates ({mining.max_templates:,}) was reached; extra records were pooled "
                f"into catch-all templates ({hint})"
            )
        if summary.records == 0:
            warnings.append(f"{summary.name}: no records were parsed")
    if resolved.multiline_auto:
        warnings.append("indented continuation lines were found; multiline was enabled automatically")
    elif resolved.confidence is not None and resolved.confidence < 1.0:
        warnings.append(
            f"the detected format matched {resolved.confidence:.0%} of sampled lines; "
            "unmatched lines may be continuations (try multiline=True)"
        )
    return warnings


def _ignored_chunk_options(execution: ExecutionConfig, high_cardinality: bool) -> list[str]:
    """Name the options that only matter for the chunked strategy when the run was sequential.

    ``warm_start`` is always reported. ``chunk_bytes`` is reported only when something other than the input size made
    the run sequential, because with ``strategy="auto"`` it is also the size above which the input is chunked.
    """
    forced = True
    if high_cardinality:
        reason = "high_cardinality runs sequentially"
    elif execution.strategy == "sequential":
        reason = "strategy='sequential' was asked for"
    else:
        forced = False
        reason = "the input was small enough for one tree; strategy='chunked' forces chunks"
    ignored = []
    if execution.warm_start:
        ignored.append("warm_start")
    if forced and execution.chunk_bytes != DEFAULT_CHUNK_BYTES:
        ignored.append("chunk_bytes")
    return [
        f"{name} was ignored: it applies to the chunked strategy, but the run was sequential ({reason})"
        for name in ignored
    ]


def _meta(spec: FormatSpec, mining: MiningConfig) -> ResultMeta:
    return ResultMeta(
        schema_version=SCHEMA_VERSION,
        algo_version=ALGO_VERSION,
        logfold_version=get_version(),
        config_hash=config_fingerprint(mining, spec),
        format=spec.name,
        degraded=False,
    )
