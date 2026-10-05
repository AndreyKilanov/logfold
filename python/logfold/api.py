"""Public facade: :func:`analyze` and :func:`diff`.

The facade turns user options into frozen configuration, picks an engine, runs one mining call and converts the
engine's plain-data answer into the public result model.
"""

from __future__ import annotations

import codecs
import dataclasses
import json
import logging
import os
import time
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
from logfold.engines.base import Engine, MineRequest, MiningResult, RunInfo, RunStatsData, TemplateStats
from logfold.engines.select import select_engine
from logfold.errors import ConfigError, SourceError
from logfold.ext import registry
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.masks import Masker, validate_masks
from logfold.formats import ResolvedFormat, resolve_format
from logfold.model import (
    LEVEL_NAMES,
    SCHEMA_VERSION,
    AnalysisResult,
    DiffResult,
    ResultMeta,
    RunMetrics,
    RunSummary,
    Template,
    datetime_to_micros,
    micros_to_datetime,
    summarize_levels,
)
from logfold.reporters.payload import analysis_from_payload

logger = logging.getLogger("logfold")

PathLike = str | os.PathLike[str]
Progress = Callable[[int], None]
UNPARSED_WARNING_RATIO = 0.10
ALGO_VERSION = 1
MAX_REPORT_BYTES = 256 << 20


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


def load_analysis(path: PathLike) -> AnalysisResult:
    """Load an analysis result saved as a JSON report (``AnalysisResult.to_json()`` or ``--out result.json``).

    Args:
        path: The JSON report (UTF-8, at most 256 MiB). It must hold every template, so it must not have been
            written with a ``limit``.

    Returns:
        The analysis result, ready for :func:`diff`.

    Raises:
        SourceError: If the file cannot be read or is not a complete analysis report of a supported version.
    """
    name = os.fspath(path)
    try:
        size = os.stat(path).st_size
        if size > MAX_REPORT_BYTES:
            raise SourceError(f"{name!r} is {size:,} bytes; a report larger than {MAX_REPORT_BYTES:,} bytes is refused")
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise SourceError(f"cannot read an analysis report from {name!r}: {error}") from error
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise SourceError(
            f"{name!r} is UTF-16 text (a PowerShell 5 '>' redirect does that); write the report with --out instead"
        )
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as error:
        raise SourceError(f"cannot read an analysis report from {name!r}: {error}") from error
    if not isinstance(payload, dict):
        raise SourceError(f"{name!r} is not an analysis report")
    return analysis_from_payload(payload)


_MINING_ONLY_DEFAULTS: dict[str, Any] = {
    "format": "auto",
    "multiline": None,
    "recount": None,
    "depth": None,
    "sim_th": None,
    "max_children": None,
    "max_templates": None,
    "masks": None,
    "high_cardinality": False,
    "mining": None,
    "execution": None,
    "engine": None,
    "strategy": None,
    "threads": None,
    "chunk_bytes": None,
    "progress": None,
}


def _diff_config(
    base: DiffConfig | None,
    threshold_ratio: float | None,
    min_count: int | None,
    min_new_count: int | None,
    recount: bool | None,
    matcher: str | None,
) -> DiffConfig:
    config = base or DiffConfig()
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
    return dataclasses.replace(config, **changes) if changes else config


def _saved_stats(template: Template | None) -> RunStatsData:
    if template is None:
        return RunStatsData(0, None, None, (0,) * len(LEVEL_NAMES), None)
    return RunStatsData(
        count=template.count,
        first=datetime_to_micros(template.first_seen),
        last=datetime_to_micros(template.last_seen),
        levels=tuple(template.levels.get(name, 0) for name in LEVEL_NAMES),
        example=template.example,
    )


def _join_saved(before: AnalysisResult, after: AnalysisResult) -> list[TemplateStats]:
    first = {template.id: template for template in before.templates}
    second = {template.id: template for template in after.templates}
    joined: list[TemplateStats] = []
    for key in {**first, **second}:
        present = second.get(key) or first[key]
        runs = (_saved_stats(first.get(key)), _saved_stats(second.get(key)))
        joined.append(TemplateStats(id=present.id, text=present.text, runs=runs))
    return joined


def _saved_warnings(before: AnalysisResult, after: AnalysisResult) -> list[str]:
    warnings = [
        "saved results were mined separately and are not re-counted against a shared template tree; the same "
        "event may be reported as new and disappeared (try matcher='token_subset')"
    ]
    if before.meta.config_hash != after.meta.config_hash:
        warnings.append(
            f"the results were mined with different masks or parameters ({before.meta.config_hash} and "
            f"{after.meta.config_hash}); their templates may not be comparable"
        )
    if before.meta.format != after.meta.format:
        warnings.append(f"the results use different formats ({before.meta.format!r} and {after.meta.format!r})")
    for summary in (before.run, after.run):
        if summary.overflowed:
            warnings.append(
                f"{summary.name}: max_templates was reached; extra records were pooled into catch-all templates"
            )
        if summary.records == 0:
            warnings.append(f"{summary.name}: no records were parsed")
    return warnings


def _diff_saved(
    before: AnalysisResult, after: AnalysisResult, config: DiffConfig, examples: ExamplesMode
) -> DiffResult:
    started = time.perf_counter()
    if examples == "masked":
        raise ConfigError(
            "examples='masked' cannot be applied to saved analysis results (the masking rules are not saved); "
            "use 'none', or analyze the logs with examples='masked' before saving"
        )
    if before.meta.algo_version != after.meta.algo_version:
        raise ConfigError(
            f"the results come from different algorithm versions ({before.meta.algo_version} and "
            f"{after.meta.algo_version}) and cannot be compared; analyze both logs again"
        )
    config = dataclasses.replace(config, recount=False)
    classification = classify(
        _join_saved(before, after), before.run, after.run, config, registry.get_matcher(config.matcher)
    )
    new, gone, moved = classification.new, classification.disappeared, classification.changed
    if examples == "none":
        new = tuple(dataclasses.replace(e, example=None) for e in new)
        gone = tuple(dataclasses.replace(e, example=None) for e in gone)
        moved = tuple(dataclasses.replace(e, example=None) for e in moved)
    metrics = RunMetrics(
        engine=after.metrics.engine,
        strategy="sequential",
        threads=1,
        chunks=0,
        wall_total_s=time.perf_counter() - started,
        wall_mine_s=0.0,
        wall_merge_s=0.0,
        wall_recount_s=0.0,
        wall_freeze_s=0.0,
    )
    return DiffResult(
        new_templates=new,
        disappeared=gone,
        changed=moved,
        unchanged=classification.unchanged,
        before=before.run,
        after=after.run,
        config=config,
        metrics=metrics,
        meta=dataclasses.replace(after.meta, degraded=before.meta.degraded or after.meta.degraded),
        warnings=tuple(_saved_warnings(before, after)),
    )


def diff(
    before: PathLike | Sequence[PathLike] | AnalysisResult,
    after: PathLike | Sequence[PathLike] | AnalysisResult,
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

    Two :class:`AnalysisResult` objects (from :func:`analyze` or :func:`load_analysis`) can be compared instead of
    logs. Nothing is re-read then: templates are joined by id, one-sided ones are paired by the matcher, and the
    counts are the saved ones, so the options that control mining or reading (``format``, ``masks``, ``engine`` and
    so on) raise :class:`ConfigError`.

    Args:
        before: Input(s) of the first run, for example the log before a deploy, or its saved analysis result.
        after: Input(s) of the second run, or its saved analysis result.
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
    config = _diff_config(diff_config, threshold_ratio, min_count, min_new_count, recount, matcher)
    if isinstance(before, AnalysisResult) or isinstance(after, AnalysisResult):
        if not (isinstance(before, AnalysisResult) and isinstance(after, AnalysisResult)):
            raise ConfigError("diff() compares two analysis results or two sets of inputs, not one of each")
        given = locals()
        ignored = [name for name, default in _MINING_ONLY_DEFAULTS.items() if given[name] != default]
        if ignored:
            raise ConfigError(f"{', '.join(ignored)} cannot be used when comparing saved analysis results")
        return _diff_saved(before, after, config, examples)
    first = _paths(before, "diff() before")
    second = _paths(after, "diff() after")
    resolved = resolve_format(format, first, multiline)
    spec = resolved.spec
    mining_config = _mining(mining, depth, sim_th, max_children, max_templates, masks, high_cardinality)
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes, high_cardinality)
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
