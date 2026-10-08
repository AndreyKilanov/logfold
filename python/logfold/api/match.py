"""``match()``: assign the records of a log to the templates of a saved state, without learning anything."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence

from logfold.api._common import (
    PathLike,
    Progress,
    _execution,
    _meta,
    _mine,
    _mining,
    _paths,
    _state,
    _summary,
    _templates,
    _warnings,
)
from logfold.api._windows import OPEN, TimeBound, labeled, require_time, window, window_warnings
from logfold.config import ExamplesMode, ExecutionConfig, MaskRule, MiningConfig
from logfold.errors import ConfigError
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.masks import Masker
from logfold.formats import resolve_format
from logfold.model import AnalysisResult, Unmatched


def match(
    state: PathLike,
    path: PathLike | Sequence[PathLike],
    *,
    format: str | FormatSpec | Format = "auto",
    multiline: bool | None = None,
    depth: int | None = None,
    sim_th: float | None = None,
    max_children: int | None = None,
    max_templates: int | None = None,
    masks: Sequence[MaskRule] | None = None,
    mining: MiningConfig | None = None,
    execution: ExecutionConfig | None = None,
    engine: str | None = None,
    strategy: str | None = None,
    threads: int | None = None,
    chunk_bytes: int | None = None,
    examples: ExamplesMode = "raw",
    since: TimeBound = None,
    until: TimeBound = None,
    progress: Progress | None = None,
) -> AnalysisResult:
    """Assign the records of a log to the templates of a saved state, without learning anything.

    The state is only read. The result is an analysis of the log against the templates that the state holds: the
    templates that were hit with the counts, levels and times of this log only, and ``result.run.unmatched`` with the
    records that fit no template (counted by their length in tokens; the text of the records is not kept). The masks and
    the mining parameters must be the ones that the state was mined with.

    Args:
        state: A state file saved by ``analyze(..., save_state=...)``.
        path: One input file or several files that form a single run (``-`` is standard input).
        format: ``auto``, a registered name, ``regex:<pattern>``, a format specification or a ``Format`` object.
        multiline: Join continuation lines to the previous record; ``None`` keeps the format's default.
        depth: Tree depth of the state (default 4).
        sim_th: Similarity threshold of the state (default 0.4).
        max_children: Maximum children per tree node of the state (default 100).
        max_templates: Maximum number of templates of the state (default 100000).
        masks: Masking rules that the state was mined with, replacing the defaults.
        mining: Full mining configuration; the keyword arguments above override its fields.
        execution: Full execution configuration; the keyword arguments below override its fields.
        engine: ``auto`` or ``native``.
        strategy: ``auto``, ``sequential`` or ``chunked``; only decides whether the files are read in parallel, the
            answer is the same.
        threads: Worker threads for the chunked strategy.
        chunk_bytes: Chunk size of the chunked strategy.
        examples: ``raw`` keeps example messages, ``masked`` applies the masking rules to them, ``none`` drops them.
        since: Keep only records at or after this time; see :func:`logfold.analyze`.
        until: Keep only records before this time; see :func:`logfold.analyze`.
        progress: Optional callback receiving consumed input byte counts.

    Returns:
        The templates of the state that were hit, run counters (``run.unmatched`` is set), metrics and provenance.

    Raises:
        ConfigError: If an option is invalid.
        FormatError: If the format is invalid or cannot be detected.
        SourceError: If an input cannot be read.
        EngineError: If the requested engine is unavailable.
        StateError: If the state file is damaged, too large, newer than this logfold or mined with other settings.
    """
    run = _paths(path, "match()")
    resolved = resolve_format(format, run, multiline)
    spec = resolved.spec
    bounds = window(since, until)
    if bounds != OPEN:
        require_time(spec)
    mining_config = _mining(mining, depth, sim_th, max_children, max_templates, masks)
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes)
    saved = _state(state, None, "json", mining_config, spec)
    if saved is None:
        raise ConfigError("match() needs a state file")
    mined = _mine(
        (run,),
        spec,
        mining_config,
        exec_config,
        progress,
        windows=(bounds,) if bounds != OPEN else (),
        state=saved,
        matching=True,
    )
    by_length = mined.unmatched[0] if mined.unmatched is not None else ()
    missed = Unmatched(records=sum(records for _, records in by_length), by_length=by_length)
    summary = dataclasses.replace(labeled(_summary(run, mined.runs[0]), bounds), unmatched=missed)
    masker = Masker(mining_config.masks)
    templates = _templates(mined.templates, 0, summary.tz_aware, examples, masker)
    notes = []
    if missed.records:
        notes.append(
            f"{missed.records:,} of {summary.records:,} records ({missed.records / summary.records:.1%}) belong to no "
            f"template of the state"
        )
    return AnalysisResult(
        templates=templates,
        run=summary,
        metrics=mined.metrics,
        meta=_meta(spec, mining_config),
        warnings=(
            *_warnings([summary], exec_config, resolved, mining_config, False, mined.metrics.strategy),
            *window_warnings(summary),
            *notes,
        ),
    )
