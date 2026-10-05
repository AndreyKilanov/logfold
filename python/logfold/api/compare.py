"""``diff()``: compare two runs, either from logs or from saved analysis results."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from logfold.api._common import (
    PathLike,
    Progress,
    _example,
    _execution,
    _meta,
    _mine,
    _mining,
    _paths,
    _summary,
    _warnings,
)
from logfold.api.saved import MINING_ONLY_DEFAULTS, diff_saved
from logfold.comparison import classify
from logfold.config import (
    DiffConfig,
    ExamplesMode,
    ExecutionConfig,
    MaskRule,
    MiningConfig,
)
from logfold.errors import ConfigError
from logfold.ext import registry
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.masks import Masker
from logfold.formats import resolve_format
from logfold.model import (
    AnalysisResult,
    DiffResult,
)


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
        ignored = [name for name, default in MINING_ONLY_DEFAULTS.items() if given[name] != default]
        if ignored:
            raise ConfigError(f"{', '.join(ignored)} cannot be used when comparing saved analysis results")
        return diff_saved(before, after, config, examples)
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
