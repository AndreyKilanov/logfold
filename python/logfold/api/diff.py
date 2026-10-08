"""``diff()``: compare two runs, either from logs or from saved analysis results."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from typing import Any

from logfold.api._baselines import baseline_warnings, pool_baselines, required_baselines
from logfold.api._common import (
    PathLike,
    Progress,
    _apply_settings,
    _example,
    _execution,
    _meta,
    _mine,
    _mining,
    _paths,
    _summary,
    _warnings,
)
from logfold.api._matching import native_spec, resolve_matcher
from logfold.api._native_classify import classify_native, table_side
from logfold.api._windows import (
    OPEN,
    TimeBound,
    Window,
    labeled,
    require_time,
    split_windows,
    window,
    window_warnings,
)
from logfold.api.saved import MINING_ONLY_DEFAULTS, diff_saved
from logfold.comparison import Classification, classify
from logfold.config import (
    DiffConfig,
    ExamplesMode,
    ExecutionConfig,
    MaskRule,
    MiningConfig,
)
from logfold.errors import ConfigError
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.masks import Masker
from logfold.formats import resolve_format
from logfold.model import (
    AnalysisResult,
    DiffResult,
)
from logfold.settings import Settings


def _diff_config(
    base: DiffConfig | None,
    threshold_ratio: float | None,
    min_count: int | None,
    min_new_count: int | None,
    recount: bool | None,
    matcher: str | None,
    significance: float | None,
    min_baselines: int | None,
) -> DiffConfig:
    config = base or DiffConfig()
    changes: dict[str, Any] = {}
    for key, value in (
        ("threshold_ratio", threshold_ratio),
        ("min_count", min_count),
        ("min_new_count", min_new_count),
        ("recount", recount),
        ("matcher", matcher),
        ("significance", significance),
        ("min_baselines", min_baselines),
    ):
        if value is not None:
            changes[key] = value
    return dataclasses.replace(config, **changes) if changes else config


def _windows(since: TimeBound, until: TimeBound, split_at: TimeBound, runs: int) -> tuple[Window, ...]:
    """The windows of the runs: empty without any bound, otherwise one per run."""
    if split_at is not None:
        return split_windows(since, until, split_at)
    bounds = window(since, until)
    return (bounds,) * runs if bounds != OPEN else ()


def _baselines(
    before: tuple[str, ...], more: Sequence[PathLike | Sequence[PathLike]] | None, split_at: TimeBound
) -> tuple[tuple[str, ...], ...]:
    """The runs that form the "before" side: ``before`` and the extra baselines."""
    if not more:
        return (before,)
    if split_at is not None:
        raise ConfigError("split_at compares two parts of one input, so it cannot be combined with baselines")
    return (before, *(_paths(item, "diff() baselines") for item in more))


def diff(
    before: PathLike | Sequence[PathLike] | AnalysisResult,
    after: PathLike | Sequence[PathLike] | AnalysisResult | None = None,
    *,
    format: str | FormatSpec | Format | None = None,
    multiline: bool | None = None,
    threshold_ratio: float | None = None,
    min_count: int | None = None,
    min_new_count: int | None = None,
    recount: bool | None = None,
    matcher: str | None = None,
    significance: float | None = None,
    baselines: Sequence[PathLike | Sequence[PathLike]] | None = None,
    min_baselines: int | None = None,
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
    warm_start: bool | None = None,
    examples: ExamplesMode = "raw",
    since: TimeBound = None,
    until: TimeBound = None,
    split_at: TimeBound = None,
    config: Settings | None = None,
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
        matcher: Name of the diff matcher (default ``jaccard``).
        significance: Highest p-value of a changed template that is still reported (default 0.01; 1 keeps all).
        baselines: More baseline runs, each an input or a sequence of inputs, besides ``before``. All baselines are
            pooled into the first side (counts and records added up, shares normalized by the pooled records), so a
            template is new only if it occurs in none of them. Logs only: not for analysis results or ``split_at``.
        min_baselines: With ``baselines``, the number of baselines a template must occur in to be reported as
            disappeared or changed (default: all); a template in fewer baselines is unstable and is not reported.
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
        warm_start: Chunked strategy only; see :func:`analyze`.
        examples: ``raw``, ``masked`` or ``none``; see :func:`analyze`.
        since: Keep only records at or after this time, in both runs; see :func:`analyze`. With ``split_at`` it is the
            start of the first run.
        until: Keep only records before this time, in both runs. With ``split_at`` it is the end of the second run.
        split_at: Compare two parts of one input: ``before`` is the only input, the records before this time are the
            first run and the records from this time on are the second run (``after`` is left out). The input is read
            once for each run and one template tree is shared, as for two inputs.
        config: Settings from a ``logfold.toml`` (:func:`logfold.load_config`): they give the format, ``multiline``, the
            mining and execution configuration and, for ``diff``, the comparison configuration, wherever the call does
            not name them itself.
        progress: Optional callback receiving consumed input byte counts.

    Returns:
        New, disappeared and changed templates with counts and shares.

    Raises:
        ConfigError: If an option is invalid.
        FormatError: If the format is invalid or cannot be detected.
        SourceError: If an input cannot be read.
        EngineError: If the requested engine is unavailable.
    """
    compare = _diff_config(
        diff_config if diff_config is not None or config is None else config.diff,
        threshold_ratio,
        min_count,
        min_new_count,
        recount,
        matcher,
        significance,
        min_baselines,
    )
    resolved_matcher = resolve_matcher(compare.matcher)
    if after is None:
        if split_at is None:
            raise ConfigError("diff() needs two inputs, or one input and split_at")
        after = before
    elif split_at is not None:
        raise ConfigError("split_at compares two parts of one input: give one input and no 'after'")
    if isinstance(before, AnalysisResult) or isinstance(after, AnalysisResult):
        if baselines:
            raise ConfigError("baselines can only be used with logs, not with saved analysis results")
        if compare.min_baselines is not None:
            raise ConfigError("min_baselines can only be used with baselines")
        if not (isinstance(before, AnalysisResult) and isinstance(after, AnalysisResult)):
            raise ConfigError("diff() compares two analysis results or two sets of inputs, not one of each")
        given = locals()
        ignored = [
            name
            for name, default in MINING_ONLY_DEFAULTS.items()
            if given[name] != default and not (name == "format" and given[name] is None)
        ]
        if ignored:
            raise ConfigError(f"{', '.join(ignored)} cannot be used when comparing saved analysis results")
        return diff_saved(before, after, compare, examples)
    first = _paths(before, "diff() before")
    second = _paths(after, "diff() after")
    format, multiline, mining, execution = _apply_settings(config, format, multiline, mining, execution)
    resolved = resolve_format(format, first, multiline)
    spec = resolved.spec
    runs = (*_baselines(first, baselines, split_at), second)
    windows = _windows(since, until, split_at, len(runs))
    if windows:
        require_time(spec)
    if split_at is not None and "-" in first:
        raise ConfigError(
            "split_at reads the input once for each run, so it cannot read standard input; save it to a file"
        )
    mining_config = _mining(mining, depth, sim_th, max_children, max_templates, masks, high_cardinality)
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes, high_cardinality, warm_start)
    mined = _mine(runs, spec, mining_config, exec_config, progress, compare.recount, windows)
    pooled = pool_baselines(mined, len(runs) - 1, required_baselines(len(runs) - 1, compare.min_baselines))
    table = pooled.table
    before_names = tuple(name for run in runs[:-1] for name in run)
    before_summary = labeled(_summary(before_names, pooled.before), windows[0] if windows else OPEN)
    after_summary = labeled(_summary(second, pooled.after), windows[-1] if windows else OPEN)
    masker = Masker(mining_config.masks)
    native_matcher = native_spec(resolved_matcher)
    classification = None
    if native_matcher is not None:
        classification = classify_native(
            table_side(table, 0, before_summary),
            table_side(table, 1, after_summary),
            compare,
            native_matcher,
            lambda text: _example(text, examples, masker),
        )
    reported = classification
    if reported is None:
        reported = classify(
            list(table),
            before_summary,
            after_summary,
            compare,
            resolved_matcher,
        )

        def scrub(entries: tuple) -> tuple:  # type: ignore[type-arg]
            return tuple(dataclasses.replace(e, example=_example(e.example, examples, masker)) for e in entries)

        reported = Classification(
            scrub(reported.new), scrub(reported.disappeared), scrub(reported.changed), reported.unchanged
        )
    unchanged = reported.unchanged + pooled.unstable

    return DiffResult(
        new_templates=reported.new,
        disappeared=reported.disappeared,
        changed=reported.changed,
        unchanged=unchanged,
        before=before_summary,
        after=after_summary,
        config=compare,
        metrics=mined.metrics,
        meta=_meta(spec, mining_config),
        warnings=(
            *_warnings(
                [before_summary, after_summary],
                exec_config,
                resolved,
                mining_config,
                high_cardinality,
                mined.metrics.strategy,
            ),
            *baseline_warnings(runs[:-1], mined.runs[:-1]),
            *window_warnings(before_summary),
            *window_warnings(after_summary),
        ),
    )
