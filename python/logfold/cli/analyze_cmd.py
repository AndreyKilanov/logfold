"""The ``logfold analyze`` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

import logfold
from logfold.cli.levels import analysis_note, resolve_level
from logfold.cli.options import (
    PANEL_OUTPUT,
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
    LoadState,
    MaxChildren,
    MaxTemplates,
    Multiline,
    NoMasks,
    OnlyAlerts,
    Out,
    Quiet,
    Report,
    SaveState,
    SimTh,
    Since,
    StateForm,
    Strategy,
    Threads,
    Top,
    Until,
    WarmStart,
    mining_options,
)
from logfold.cli.output import resolve_outputs
from logfold.cli.runtime import config_note, emit, fail, note, progress_reporter, settings_of, write_report
from logfold.errors import LogfoldError
from logfold.ext.text import printable

EXAMPLES = """Examples:

  logfold analyze app.log

  logfold analyze app.log.1.gz app.log -o report.html

  logfold analyze app.log -f nginx --top 50 --json > result.json

  logfold analyze app.log --since 2026-10-06T12:00 --until 2026-10-06T13:00

  cat app.log | logfold analyze - -f plain"""


def analyze(
    ctx: typer.Context,
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
    engine: Engine = None,
    chunk_mb: ChunkMb = None,
    strategy: Strategy = None,
    no_masks: NoMasks = False,
    high_cardinality: HighCardinality = False,
    warm_start: WarmStart = False,
    examples: Examples = "raw",
    load_state: LoadState = None,
    save_state: SaveState = None,
    state_format: StateForm = "json",
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Fold FILES into message templates and count them."""
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        outputs = resolve_outputs("analysis", out, report, as_json, append)
        threshold = resolve_level(level, only_alerts)
        with progress_reporter(quiet) as progress:
            result = logfold.analyze(
                [str(f) for f in files],
                format=format,
                multiline=multiline,
                since=since,
                until=until,
                examples=examples,  # type: ignore[arg-type]
                load_state=load_state,
                save_state=save_state,
                state_format=state_format,
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
        if save_state is not None:
            note(f"saved the state to {printable(str(save_state))}", quiet)
        shown = result
        if threshold is not None:
            shown = result.filter(min_level=threshold)
            note(analysis_note(result, shown, threshold), quiet)
        if min_count > 1:
            shown = shown.filter(min_count=min_count)
        emit(shown, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(result if outputs.file == "json" else shown, out, outputs.file, quiet, append)
    except LogfoldError as error:
        raise fail(error, debug) from None
