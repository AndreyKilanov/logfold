"""Public facade: :func:`analyze` and :func:`diff`.

The facade turns user options into frozen configuration, picks an engine, runs one mining call and converts the
engine's plain-data answer into the public result model.
"""

from __future__ import annotations

import dataclasses
import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from logfold._version import get_version
from logfold.comparison import classify
from logfold.config import (
    HIGH_CARDINALITY_MAX_TEMPLATES,
    DiffConfig,
    ExamplesMode,
    ExecutionConfig,
    MaskRule,
    MiningConfig,
    config_fingerprint,
)
from logfold.engines import native
from logfold.engines.base import Engine, MineRequest, MiningResult, RunInfo, TemplateStats
from logfold.engines.select import select_engine
from logfold.errors import ConfigError, SourceError
from logfold.ext import registry
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.masks import Masker, validate_masks
from logfold.formats import ResolvedFormat, resolve_format
from logfold.model import (
    SCHEMA_VERSION,
    AnalysisResult,
    DiffResult,
    ResultMeta,
    RunSummary,
    Template,
    micros_to_datetime,
    summarize_levels,
)

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
) -> ExecutionConfig:
    config = base or ExecutionConfig()
    if high_cardinality and strategy is None and config.strategy == "auto":
        strategy = "sequential"
    changes: dict[str, Any] = {}
    for key, value in (("engine", engine), ("strategy", strategy), ("threads", threads), ("chunk_bytes", chunk_bytes)):
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
                    raise SourceError(f"cannot read {path!r}: {error}") from error
    return total


def _resolve_strategy(engine: Engine, execution: ExecutionConfig, runs: tuple[tuple[str, ...], ...]) -> str:
    if engine.name == "python":
        if execution.strategy == "chunked":
            logger.warning("the pure-Python engine is always sequential; ignoring strategy='chunked'")
        return "sequential"
    if execution.strategy != "auto":
        return execution.strategy
    return "chunked" if _total_size(runs) > execution.chunk_bytes else "sequential"


def _mine(
    runs: tuple[tuple[str, ...], ...],
    spec: FormatSpec,
    mining: MiningConfig,
    execution: ExecutionConfig,
    progress: Progress | None,
    recount: bool = False,
) -> tuple[MiningResult, Engine]:
    engine = select_engine(execution)
    request = MineRequest(
        runs=runs,
        format=spec,
        mining=mining,
        strategy=_resolve_strategy(engine, execution, runs),
        threads=execution.threads,
        chunk_bytes=execution.chunk_bytes,
        recount=recount,
    )
    return engine.mine(request, progress), engine


def _summary(paths: tuple[str, ...], info: RunInfo) -> RunSummary:
    return RunSummary(
        name=",".join(paths),
        files=info.files,
        lines=info.lines,
        records=info.records,
        unparsed=info.unparsed,
        bytes=info.bytes,
        tz_aware=info.tz_aware,
        overflowed=info.overflowed,
    )


def _example(text: str | None, mode: ExamplesMode, masker: Masker) -> str | None:
    if text is None or mode == "none":
        return None
    return masker.mask(text) if mode == "masked" else text


def _template(stats: TemplateStats, run: int, tz_aware: bool, mode: ExamplesMode, masker: Masker) -> Template:
    data = stats.runs[run]
    level, levels = summarize_levels(data.levels)
    return Template(
        id=stats.id,
        text=stats.text,
        count=data.count,
        first_seen=micros_to_datetime(data.first, tz_aware),
        last_seen=micros_to_datetime(data.last, tz_aware),
        example=_example(data.example, mode, masker),
        level=level,
        levels=levels,
    )


def _warnings(
    summaries: Sequence[RunSummary],
    engine: Engine,
    execution: ExecutionConfig,
    resolved: ResolvedFormat,
    mining: MiningConfig,
    high_cardinality: bool,
) -> list[str]:
    warnings: list[str] = []
    if engine.name == "python" and not native.is_available():
        warnings.append("the native extension is unavailable; the slow pure-Python engine was used")
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


def _meta(spec: FormatSpec, mining: MiningConfig, engine: Engine) -> ResultMeta:
    return ResultMeta(
        schema_version=SCHEMA_VERSION,
        algo_version=ALGO_VERSION,
        logfold_version=get_version(),
        config_hash=config_fingerprint(mining, spec),
        format=spec.name,
        degraded=engine.name == "python",
    )


def analyze(
    path: PathLike | Sequence[PathLike],
    *,
    format: str | FormatSpec | Format = "auto",
    multiline: bool | None = None,
    depth: int | None = None,
    sim_th: float | None = None,
    max_children: int | None = None,
    max_templates: int | None = None,
    masks: Sequence[MaskRule] | None = None,
    high_cardinality: bool = False,
    mining: MiningConfig | None = None,
    execution: ExecutionConfig | None = None,
    engine: str | None = None,
    strategy: str | None = None,
    threads: int | None = None,
    chunk_bytes: int | None = None,
    examples: ExamplesMode = "raw",
    progress: Progress | None = None,
) -> AnalysisResult:
    """Fold a log into templates.

    Args:
        path: One input file or several files that form a single run (``-`` is standard input).
        format: ``auto``, a registered name, ``regex:<pattern>``, a format specification or a ``Format`` object.
        multiline: Join continuation lines to the previous record; ``None`` keeps the format's default.
        depth: Tree depth (default 4, Drain3 convention).
        sim_th: Similarity threshold (default 0.4).
        max_children: Maximum children per tree node (default 100).
        max_templates: Maximum number of templates before pooling (default 100000).
        masks: Masking rules replacing the defaults.
        high_cardinality: Mode for data with a huge number of distinct message shapes (unstructured text, random ids):
            caps templates at 5000 unless ``max_templates`` is given, pools the rest into catch-all templates and
            runs sequentially. Much faster and bounded in memory; rare templates are not kept apart.
        mining: Full mining configuration; the keyword arguments above override its fields.
        execution: Full execution configuration; the keyword arguments below override its fields.
        engine: ``auto``, ``native`` or ``python``.
        strategy: ``auto``, ``sequential`` or ``chunked``.
        threads: Worker threads for the chunked strategy.
        chunk_bytes: Chunk size of the chunked strategy.
        examples: ``raw`` keeps example messages, ``masked`` applies the masking rules to them, ``none`` drops them.
        progress: Optional callback receiving consumed input byte counts.

    Returns:
        The templates, run counters, metrics and provenance.

    Raises:
        ConfigError: If an option is invalid.
        FormatError: If the format is invalid or cannot be detected.
        SourceError: If an input cannot be read.
        EngineError: If the requested engine is unavailable.
    """
    run = _paths(path, "analyze()")
    resolved = resolve_format(format, run, multiline)
    spec = resolved.spec
    mining_config = _mining(mining, depth, sim_th, max_children, max_templates, masks, high_cardinality)
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes, high_cardinality)
    mined, used = _mine((run,), spec, mining_config, exec_config, progress)
    summary = _summary(run, mined.runs[0])
    masker = Masker(mining_config.masks)
    templates = tuple(
        _template(stats, 0, summary.tz_aware, examples, masker) for stats in mined.templates if stats.runs[0].count > 0
    )
    return AnalysisResult(
        templates=templates,
        run=summary,
        metrics=mined.metrics,
        meta=_meta(spec, mining_config, used),
        warnings=tuple(_warnings([summary], used, exec_config, resolved, mining_config, high_cardinality)),
    )


def diff(
    before: PathLike | Sequence[PathLike],
    after: PathLike | Sequence[PathLike],
    *,
    format: str | FormatSpec | Format = "auto",
    multiline: bool | None = None,
    threshold_ratio: float | None = None,
    min_count: int | None = None,
    min_new_count: int | None = None,
    recount: bool | None = None,
    matcher: str | None = None,
    diff_config: DiffConfig | None = None,
    depth: int | None = None,
    sim_th: float | None = None,
    max_children: int | None = None,
    max_templates: int | None = None,
    masks: Sequence[MaskRule] | None = None,
    high_cardinality: bool = False,
    mining: MiningConfig | None = None,
    execution: ExecutionConfig | None = None,
    engine: str | None = None,
    strategy: str | None = None,
    threads: int | None = None,
    chunk_bytes: int | None = None,
    examples: ExamplesMode = "raw",
    progress: Progress | None = None,
) -> DiffResult:
    """Compare two runs of a log: what appeared, disappeared or changed its share.

    Both runs are mined with one shared template tree, so a template that occurs in both is the same template.
    Shares are normalized by the number of records in each run.

    Args:
        before: Input(s) of the first run, for example the log before a deploy.
        after: Input(s) of the second run.
        format: Format of both runs; ``auto`` detects it from the first input of ``before``.
        multiline: Join continuation lines to the previous record.
        threshold_ratio: Minimum factor by which a share must change to be reported as changed (default 2.0).
        min_count: Minimum records, in either run, for a template to be reported as changed (default 10).
        min_new_count: Minimum records for a template to be reported as new or disappeared (default 1).
        recount: Assign records to the finished template tree for consistent counts (default True; costs a second
            pass over the inputs).
        matcher: Name of the diff matcher (default ``exact``).
        diff_config: Full comparison configuration; the keyword arguments above override its fields.
        depth: Tree depth.
        sim_th: Similarity threshold.
        max_children: Maximum children per tree node.
        max_templates: Maximum number of templates before pooling.
        masks: Masking rules replacing the defaults.
        high_cardinality: Fast mode for data with a huge number of distinct message shapes; see :func:`analyze`.
        mining: Full mining configuration.
        execution: Full execution configuration.
        engine: ``auto``, ``native`` or ``python``.
        strategy: ``auto``, ``sequential`` or ``chunked``.
        threads: Worker threads for the chunked strategy.
        chunk_bytes: Chunk size of the chunked strategy.
        examples: ``raw``, ``masked`` or ``none``; see :func:`analyze`.
        progress: Optional callback receiving consumed input byte counts.

    Returns:
        New, disappeared and changed templates with counts and shares.

    Raises:
        ConfigError: If an option is invalid.
        FormatError: If the format is invalid or cannot be detected.
        SourceError: If an input cannot be read.
        EngineError: If the requested engine is unavailable.
    """
    first = _paths(before, "diff() before")
    second = _paths(after, "diff() after")
    resolved = resolve_format(format, first, multiline)
    spec = resolved.spec
    mining_config = _mining(mining, depth, sim_th, max_children, max_templates, masks, high_cardinality)
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes, high_cardinality)
    base = diff_config or DiffConfig()
    changes: dict[str, Any] = {}
    for key, value in (
        ("threshold_ratio", threshold_ratio),
        ("min_count", min_count),
        ("min_new_count", min_new_count),
        ("recount", recount),
        ("matcher", matcher),
    ):
        if value is not None:
            changes[key] = value
    config = dataclasses.replace(base, **changes) if changes else base
    mined, used = _mine((first, second), spec, mining_config, exec_config, progress, config.recount)
    before_summary = _summary(first, mined.runs[0])
    after_summary = _summary(second, mined.runs[1])
    classification = classify(
        mined.templates, before_summary, after_summary, config, registry.get_matcher(config.matcher)
    )
    masker = Masker(mining_config.masks)

    def scrub(entries: tuple) -> tuple:  # type: ignore[type-arg]
        return tuple(dataclasses.replace(e, example=_example(e.example, examples, masker)) for e in entries)

    return DiffResult(
        new_templates=scrub(classification.new),
        disappeared=scrub(classification.disappeared),
        changed=scrub(classification.changed),
        unchanged=classification.unchanged,
        before=before_summary,
        after=after_summary,
        config=config,
        metrics=mined.metrics,
        meta=_meta(spec, mining_config, used),
        warnings=tuple(
            _warnings([before_summary, after_summary], used, exec_config, resolved, mining_config, high_cardinality)
        ),
    )
