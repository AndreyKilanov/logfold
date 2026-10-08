"""The ``logfold match`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

import logfold
from logfold.cli.levels import analysis_note, resolve_level
from logfold.cli.options import (
    PANEL_INPUT,
    PANEL_OUTPUT,
    Append,
    AsJson,
    ChunkMb,
    Debug,
    Depth,
    Examples,
    Format,
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
    mining_options,
)
from logfold.cli.output import resolve_outputs
from logfold.cli.runtime import config_note, emit, fail, note, progress_reporter, settings_of, write_report
from logfold.errors import LogfoldError

EXAMPLES = """Examples:

  logfold analyze baseline.log --save-state model.json

  logfold match model.json app.log

  logfold match model.json app.log.1.gz app.log -o report.html

  logfold match model.json app.log --json > matched.json"""

NOT_FOR_MATCH = ("engine", "high_cardinality", "warm_start")


def match(
    ctx: typer.Context,
    state: Annotated[
        Path,
        typer.Argument(
            metavar="STATE",
            help="State file saved by 'logfold analyze --save-state'; it is only read.",
            rich_help_panel=PANEL_INPUT,
        ),
    ],
    files: Annotated[list[Path], typer.Argument(help="Log files forming one run ('-' reads standard input).")],
    format: Format = "auto",
    multiline: Multiline = None,
    since: Since = None,
    until: Until = None,
    top: Top = 20,
    min_count: Annotated[
        int,
        typer.Option(
            "--min-count",
            min=1,
            help="Hide templates with fewer records; a .json file from --out stays complete.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = 1,
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
    chunk_mb: ChunkMb = None,
    strategy: Strategy = None,
    no_masks: NoMasks = False,
    examples: Examples = "raw",
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Assign FILES to the templates of a saved STATE and count the records that fit none; nothing is learned."""
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        outputs = resolve_outputs("analysis", out, report, as_json, append)
        threshold = resolve_level(level, only_alerts)
        options = mining_options(
            sim_th, depth, max_children, max_templates, threads, None, chunk_mb, strategy, no_masks, False, False
        )
        for name in NOT_FOR_MATCH:
            del options[name]
        with progress_reporter(quiet) as progress:
            result = logfold.match(
                state,
                [str(f) for f in files],
                format=format,
                multiline=multiline,
                since=since,
                until=until,
                examples=examples,  # type: ignore[arg-type]
                progress=progress,
                config=settings,
                **options,
            )
        shown = result
        if threshold is not None:
            shown = result.filter(min_level=threshold)
        if min_count > 1:
            shown = shown.filter(min_count=min_count)
        if threshold is not None:
            note(analysis_note(result, shown, threshold), quiet)
        emit(shown, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(result if outputs.file == "json" else shown, out, outputs.file, quiet, append)
    except LogfoldError as error:
        raise fail(error, debug) from None
