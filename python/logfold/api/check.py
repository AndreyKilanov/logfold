"""``check()``: compare a log with a saved model and say whether it holds anything that the model does not know."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Sequence
from typing import Literal, cast

from logfold.api._common import (
    PathLike,
    Progress,
    _apply_settings,
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
from logfold.api.diff import _diff_config
from logfold.api.saved import diff_saved
from logfold.config import DiffConfig, ExamplesMode, ExecutionConfig, MiningConfig
from logfold.engines.base import MiningResult
from logfold.errors import ConfigError
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.mask_selection import MaskSelection
from logfold.ext.masks import Masker
from logfold.formats import resolve_format
from logfold.model import AnalysisResult, DiffResult, RunSummary, Unmatched
from logfold.model_check import CheckResult, Finding
from logfold.settings import Settings

FailOn = Literal["new-alerts", "new", "none"]
DEFAULT_MAX_UNMATCHED = 1.0
FAIL_ON_CHOICES = ("new-alerts", "new", "none")


def _model_result(mined: MiningResult, summary: RunSummary, state: str, after: AnalysisResult) -> AnalysisResult:
    """The templates of the model with the counts that it saved, as the analysis of a run that was read earlier."""
    table = mined.model
    assert table is not None
    templates = _templates(table, 0, summary.tz_aware, "none", Masker(()))
    records = sum(template.count for template in templates)
    run = RunSummary(
        name=os.fspath(state), files=1, lines=records, records=records, unparsed=0, bytes=0, tz_aware=summary.tz_aware,
        overflowed=False,
    )  # fmt: skip
    return dataclasses.replace(after, templates=templates, run=run, warnings=())


def _findings(
    result: DiffResult, unmatched: Unmatched, max_unmatched: float | None, fail_on: str
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    records = result.after.records
    if records == 0:
        findings.append(Finding("empty", "no record was parsed, so nothing was checked", 0.0))
        return tuple(findings)
    share = 100.0 * unmatched.records / records
    if max_unmatched is not None and share > max_unmatched:
        findings.append(
            Finding(
                "unmatched",
                f"{unmatched.records:,} of {records:,} records ({share:.2f}%) fit no template of the model; "
                f"the limit is {max_unmatched:g}%",
                share,
                max_unmatched,
            )
        )
    gated = {"new-alerts": result.new_alerts, "new": result.new_templates, "none": ()}[fail_on]
    if gated:
        noun = "new template" if len(gated) == 1 else "new templates"
        level = "" if fail_on == "new" else " of level WARN or higher"
        findings.append(Finding("new", f"{len(gated):,} {noun}{level} that the model does not have", float(len(gated))))
    return tuple(findings)


def check(
    state: PathLike,
    path: PathLike | Sequence[PathLike],
    *,
    max_unmatched: float | str | None = "default",
    fail_on: FailOn | None = None,
    threshold_ratio: float | None = None,
    min_count: int | None = None,
    significance: float | None = None,
    diff_config: DiffConfig | None = None,
    format: str | FormatSpec | Format | None = None,
    multiline: bool | None = None,
    depth: int | None = None,
    sim_th: float | None = None,
    max_children: int | None = None,
    max_templates: int | None = None,
    on_full: str | None = None,
    delimiters: str | None = None,
    masks: MaskSelection | None = None,
    mining: MiningConfig | None = None,
    execution: ExecutionConfig | None = None,
    engine: str | None = None,
    strategy: str | None = None,
    threads: int | None = None,
    chunk_bytes: int | None = None,
    examples: ExamplesMode = "raw",
    since: TimeBound = None,
    until: TimeBound = None,
    config: Settings | None = None,
    progress: Progress | None = None,
) -> CheckResult:
    """Check a log against a saved model: does it hold anything that the model does not know?

    The model is a state file saved by ``analyze(..., save_state=...)``; it is only read. The records are matched to its
    templates, and the records that fit none are mined by themselves, which gives the templates that are new to the
    model, with their levels. The check fails (``result.passed`` is ``False``) for each of these findings: more than
    ``max_unmatched`` percent of the records fit no template, new templates of the level that ``fail_on`` names, or no
    record was parsed. A significant move of the share of a known template is reported in ``result.diff.changed`` but
    is not a finding. The masks and the mining parameters must be the ones that the state was mined with.

    Args:
        state: A state file saved by ``analyze(..., save_state=...)``, mined with ``on_full='pool'``.
        path: One input file or several files that form a single run (``-`` is standard input).
        max_unmatched: The highest share of records, in percent, that may fit no template of the model; ``None`` or
            ``"off"`` does not check it. The default is the ``[check]`` setting of ``config``, or 1.
        fail_on: ``new-alerts`` (a new template of level WARN, ERROR or FATAL is a finding), ``new`` (any new template)
            or ``none`` (new templates are only reported). The default is the ``[check]`` setting of ``config``, or
            ``new-alerts``.
        threshold_ratio: Minimum change of a template's share to be reported as ``changed``; see :func:`logfold.diff`.
        min_count: Minimum record count for a template to be reported as ``changed``.
        significance: Highest p-value of a ``changed`` template that is still reported (default 0.01).
        diff_config: Full comparison configuration; the keyword arguments above override its fields. Its ``matcher``
            and ``recount`` are ignored: a new template is one that the model does not have.
        format: ``auto``, a registered name, ``regex:<pattern>``, a format specification or a ``Format`` object.
        multiline: Join continuation lines to the previous record; ``None`` keeps the format's default.
        depth: Tree depth of the state (default 4).
        sim_th: Similarity threshold of the state (default 0.4).
        max_children: Maximum children per tree node of the state (default 100).
        max_templates: Maximum number of templates of the state (default 100000); it also bounds the new templates.
        on_full: Must be ``pool`` (the default): a state that evicts templates is refused.
        delimiters: The characters that separate tokens; the state must have been mined with the same ones.
        masks: The masks that the state was mined with: rules, or mask sets and names such as ``"secrets"``.
        mining: Full mining configuration; the keyword arguments above override its fields.
        execution: Full execution configuration; the log is read in one pass whatever the strategy.
        engine: ``auto`` or ``native``.
        strategy: ``auto``, ``sequential`` or ``chunked``; ignored.
        threads: Worker threads; ignored.
        chunk_bytes: Chunk size; ignored.
        examples: ``raw`` keeps example messages, ``masked`` applies the masking rules to them, ``none`` drops them.
        since: Keep only records at or after this time; see :func:`logfold.analyze`.
        until: Keep only records before this time; see :func:`logfold.analyze`.
        config: Settings from a ``logfold.toml`` (:func:`logfold.load_config`): they give the format, ``multiline``, the
            mining and execution configuration and the comparison configuration wherever the call does not name them.
        progress: Optional callback receiving consumed input byte counts.

    Returns:
        The findings (none when the check passed), the unmatched records and the log compared with the model.

    Raises:
        ConfigError: If an option is invalid or the state evicts templates.
        FormatError: If the format is invalid or cannot be detected.
        SourceError: If an input cannot be read.
        EngineError: If the requested engine is unavailable.
        StateError: If the state file is damaged, too large, newer than this logfold or mined with other settings.
    """
    if max_unmatched == "default":
        given = None if config is None else config.check_max_unmatched
        max_unmatched = DEFAULT_MAX_UNMATCHED if given is None else given
    if fail_on is None:
        fail_on = cast(FailOn, "new-alerts" if config is None or config.check_fail_on is None else config.check_fail_on)
    if fail_on not in FAIL_ON_CHOICES:
        raise ConfigError(f"fail_on must be one of {', '.join(FAIL_ON_CHOICES)}, found {fail_on!r}")
    limit = _limit(max_unmatched)
    compare = dataclasses.replace(
        _diff_config(
            diff_config if diff_config is not None or config is None else config.diff,
            threshold_ratio,
            min_count,
            None,
            None,
            None,
            significance,
            None,
        ),
        matcher="exact",
        recount=False,
    )
    run = _paths(path, "check()")
    format, multiline, mining, execution = _apply_settings(config, format, multiline, mining, execution)
    resolved = resolve_format(format, run, multiline)
    spec = resolved.spec
    bounds = window(since, until)
    if bounds != OPEN:
        require_time(spec)
    mining_config = _mining(
        mining, depth, sim_th, max_children, max_templates, masks, on_full=on_full, delimiters=delimiters
    )
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes)
    saved = _state(state, None, "json", mining_config, spec)
    if saved is None:
        raise ConfigError("check() needs a state file")
    mined = _mine(
        (run,),
        spec,
        mining_config,
        exec_config,
        progress,
        windows=(bounds,) if bounds != OPEN else (),
        state=saved,
        matching=True,
        checking=True,
    )
    assert mined.new_templates is not None
    by_length = mined.unmatched[0] if mined.unmatched is not None else ()
    missed = Unmatched(records=sum(records for _, records in by_length), by_length=by_length)
    summary = dataclasses.replace(labeled(_summary(run, mined.runs[0]), bounds), unmatched=missed)
    masker = Masker(mining_config.masks)
    known = _templates(mined.templates, 0, summary.tz_aware, examples, masker)
    new = _templates(mined.new_templates, 0, summary.tz_aware, examples, masker)
    after = AnalysisResult(
        templates=tuple(sorted((*known, *new), key=lambda template: (-template.count, template.text))),
        run=summary,
        metrics=mined.metrics,
        meta=_meta(spec, mining_config),
        warnings=(),
    )
    before = _model_result(mined, summary, os.fspath(state), after)
    compared = diff_saved(before, after, compare, "none" if examples == "none" else "raw")
    findings = _findings(compared, missed, limit, fail_on)
    notes = (
        *_warnings([summary], exec_config, resolved, mining_config, False, mined.metrics.strategy),
        *window_warnings(summary),
        *(f"check failed: {finding.message}" for finding in findings),
    )
    reported = dataclasses.replace(compared, disappeared=(), warnings=notes)
    return CheckResult(findings=findings, unmatched=missed, diff=reported, max_unmatched=limit, fail_on=fail_on)


def _limit(value: float | str | None) -> float | None:
    if value is None or value == "off":
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.0 <= value <= 100.0:
        raise ConfigError(f"max_unmatched must be a number from 0 to 100 (percent) or 'off', found {value!r}")
    return float(value)
