"""The ``logfold diff`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

import logfold
from logfold.cli import exit_codes
from logfold.cli.levels import diff_note, resolve_level
from logfold.cli.options import (
    PANEL_DIFF,
    PANEL_INPUT,
    Append,
    AsJson,
    ChunkMb,
    Debug,
    Depth,
    Engine,
    Examples,
    Format,
    HighCardinality,
    Level,
    MaxChildren,
    MaxTemplates,
    Multiline,
    NoMasks,
    OnlyAlerts,
    Out,
    Quiet,
    Report,
    SimTh,
    Since,
    Strategy,
    Threads,
    Top,
    Until,
    WarmStart,
    mining_options,
)
from logfold.cli.output import resolve_outputs
from logfold.cli.runtime import (
    config_note,
    emit,
    fail,
    given_on_command_line,
    note,
    progress_reporter,
    settings_of,
    write_report,
)
from logfold.errors import LogfoldError
from logfold.model import DiffResult


def _reject_mining_flags(flags: dict[str, bool]) -> None:
    given = [name for name, used in flags.items() if used]
    if given:
        raise logfold.ConfigError(f"{', '.join(given)} cannot be used when comparing saved analysis results")


def _diff_saved(before: Path, after: Path, **options: Any) -> DiffResult:
    return logfold.diff(logfold.load_analysis(before), logfold.load_analysis(after), **options)


EXAMPLES = """Examples:

  logfold diff before.log after.log

  logfold diff before.log after.log -o diff.html

  logfold diff before.log after.log --fail-on-new-alerts -q

  logfold diff before.json after.json

  logfold diff app.log --split-at 2026-10-06T12:00

  logfold diff before1.log after.log --baseline before2.log --baseline before3.log"""


def diff(
    ctx: typer.Context,
    before: Annotated[
        Path, typer.Argument(help="Log file of the first run, for example before a deploy, or a saved report.")
    ],
    after: Annotated[
        Path | None,
        typer.Argument(help="Log file of the second run, or a saved report; leave it out with --split-at."),
    ] = None,
    format: Format = "auto",
    multiline: Multiline = None,
    since: Since = None,
    until: Until = None,
    split_at: Annotated[
        str | None,
        typer.Option(
            "--split-at",
            metavar="TIME",
            help="Compare two parts of one log: records before TIME are the first run, from TIME on the second "
            "(give one file and no second argument; --since and --until bound the whole range).",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = None,
    baseline: Annotated[
        list[Path] | None,
        typer.Option(
            "--baseline",
            metavar="FILE",
            help="Another baseline log, besides the first argument; repeat it for more. The baselines are pooled: "
            "a template is new only if none of them has it.",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = None,
    min_baselines: Annotated[
        int | None,
        typer.Option(
            "--min-baselines",
            min=1,
            metavar="N",
            help="With --baseline, the number of baselines a template must occur in to be reported as disappeared "
            "or changed (default: all).",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = None,
    top: Top = 20,
    threshold_ratio: Annotated[
        float,
        typer.Option(
            "--threshold-ratio",
            min=1.0,
            help="Share change factor reported as 'changed'.",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = 2.0,
    min_count: Annotated[
        int,
        typer.Option(
            "--min-count",
            min=0,
            help="Records, in either run, needed to report 'changed' (it does not hide anything, unlike analyze).",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = 10,
    min_new_count: Annotated[
        int,
        typer.Option(
            "--min-new-count",
            min=0,
            help="Records needed to report new or disappeared.",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = 1,
    significance: Annotated[
        float,
        typer.Option(
            "--significance",
            min=0.0,
            max=1.0,
            help="Highest p-value of a 'changed' template that is still reported; 1 keeps all (see the guide).",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = 0.01,
    matcher: Annotated[
        str,
        typer.Option(
            "--matcher",
            help="How a template found in one run only is paired with a similar one in the other: "
            "jaccard, jaccard-idf, overlap, token_subset, rules:FILE (your own pairs) or exact (no pairing).",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = "jaccard",
    recount: Annotated[
        bool,
        typer.Option(
            "--recount/--no-recount",
            help="Assign records to the finished tree (slower, consistent).",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = True,
    fail_on_new: Annotated[
        bool,
        typer.Option(
            "--fail-on-new",
            help="Exit with code 2 when new templates are found.",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = False,
    fail_on_new_alerts: Annotated[
        bool,
        typer.Option(
            "--fail-on-new-alerts",
            help="Exit with code 2 when new WARN/ERROR/FATAL templates exist.",
            rich_help_panel=PANEL_DIFF,
        ),
    ] = False,
    level: Level = None,
    only_alerts: OnlyAlerts = False,
    out: Out = None,
    append: Append = False,
    report: Report = None,
    sim_th: SimTh = None,
    depth: Depth = None,
    max_children: MaxChildren = None,
    max_templates: MaxTemplates = None,
    threads: Threads = None,
    engine: Engine = None,
    chunk_mb: ChunkMb = None,
    strategy: Strategy = None,
    no_masks: NoMasks = False,
    high_cardinality: HighCardinality = False,
    warm_start: WarmStart = False,
    examples: Examples = "raw",
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Compare two runs: new, disappeared and changed templates.

    Each argument is a log file or a saved report of 'logfold analyze --out result.json'; both must be of one kind.
    With --split-at TIME, give one log file: the records before TIME are compared with the records from TIME on.
    """
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        outputs = resolve_outputs("diff", out, report, as_json, append)
        threshold = resolve_level(level, only_alerts)
        if split_at is None and after is None:
            raise logfold.ConfigError("diff needs two files, or one file and --split-at TIME")
        if split_at is not None and after is not None:
            raise logfold.ConfigError("--split-at compares two parts of one file: give one file and no second argument")
        second = after if after is not None else before
        extra = baseline or []
        for path in (before, second, *extra):
            if not path.is_file():
                raise logfold.SourceError(f"cannot read '{path}': no such file")
        if extra and (split_at is not None or any(map(logfold.is_saved_analysis, (before, second, *extra)))):
            raise logfold.ConfigError("--baseline works with log files only, not with --split-at or saved reports")
        if min_baselines is not None and not extra:
            raise logfold.ConfigError("--min-baselines needs --baseline")
        saved = (logfold.is_saved_analysis(before), logfold.is_saved_analysis(second))
        if saved[0] != saved[1]:
            raise logfold.ConfigError("diff compares two log files or two saved analysis reports, not one of each")
        if all(saved):
            _reject_mining_flags(
                {
                    "--format": given_on_command_line(ctx, "format"),
                    "--multiline/--no-multiline": multiline is not None,
                    "--no-recount": given_on_command_line(ctx, "recount") and not recount,
                    "--sim-th": sim_th is not None,
                    "--depth": depth is not None,
                    "--max-children": max_children is not None,
                    "--max-templates": max_templates is not None,
                    "--threads": threads is not None,
                    "--engine": engine is not None,
                    "--chunk-mb": chunk_mb is not None,
                    "--strategy": strategy is not None,
                    "--no-masks": no_masks,
                    "--high-cardinality": high_cardinality,
                    "--warm-start": warm_start,
                    "--since": since is not None,
                    "--until": until is not None,
                    "--split-at": split_at is not None,
                }
            )
            result = _diff_saved(
                before,
                second,
                threshold_ratio=threshold_ratio,
                min_count=min_count,
                min_new_count=min_new_count,
                significance=significance,
                matcher=matcher,
                examples=examples,
            )
        else:
            with progress_reporter(quiet) as progress:
                result = logfold.diff(
                    str(before),
                    None if split_at is not None else str(second),
                    format=format,
                    multiline=multiline,
                    since=since,
                    until=until,
                    split_at=split_at,
                    threshold_ratio=threshold_ratio,
                    min_count=min_count,
                    min_new_count=min_new_count,
                    significance=significance,
                    baselines=[str(path) for path in extra] or None,
                    min_baselines=min_baselines,
                    matcher=matcher,
                    recount=recount,
                    examples=examples,  # type: ignore[arg-type]
                    progress=progress,
                    config=settings,
                    **mining_options(
                        sim_th,
                        depth,
                        max_children,
                        max_templates,
                        threads,
                        engine,
                        chunk_mb,
                        strategy,
                        no_masks,
                        high_cardinality,
                        warm_start,
                    ),
                )
        if threshold is not None:
            filtered = result.filter(min_level=threshold)
            note(diff_note(result, filtered, threshold), quiet)
            result = filtered
        emit(result, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(result, out, outputs.file, quiet, append)
    except LogfoldError as error:
        raise fail(error, debug) from None
    if fail_on_new and result.new_templates:
        raise typer.Exit(exit_codes.NEW_TEMPLATES)
    if fail_on_new_alerts and result.new_alerts:
        raise typer.Exit(exit_codes.NEW_TEMPLATES)
