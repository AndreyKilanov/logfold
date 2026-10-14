"""The ``logfold analyze`` command."""

from __future__ import annotations

from contextlib import ExitStack
from typing import Annotated

import typer

import logfold
from logfold.api.fetch import DEFAULT_TIMEOUT
from logfold.cli.levels import analysis_note, resolve_level
from logfold.cli.options import (
    PANEL_OUTPUT,
    Append,
    AsJson,
    ChunkMb,
    Debug,
    Delimiters,
    Depth,
    Engine,
    Examples,
    Format,
    HighCardinality,
    Level,
    LoadState,
    Masks,
    MasksFile,
    MaxChildren,
    MaxTemplates,
    Multiline,
    NoMasks,
    OnFull,
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
from logfold.cli.runtime import (
    config_note,
    emit,
    examples_note,
    fail,
    note,
    progress_reporter,
    settings_of,
    write_report,
)
from logfold.cli.source_options import (
    DEFAULT_MAX_MB,
    INPUT_HELP,
    SourceArgs,
    SourceMaxMb,
    SourcePrevious,
    SourceSince,
    SourceTail,
    SourceTimeout,
    open_inputs,
)
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
    files: Annotated[list[str], typer.Argument(help=INPUT_HELP)],
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
    on_full: OnFull = None,
    delimiters: Delimiters = None,
    threads: Threads = None,
    engine: Engine = None,
    chunk_mb: ChunkMb = None,
    strategy: Strategy = None,
    no_masks: NoMasks = False,
    masks: Masks = None,
    masks_file: MasksFile = None,
    high_cardinality: HighCardinality = False,
    warm_start: WarmStart = False,
    examples: Examples = "raw",
    values: Annotated[
        bool,
        typer.Option(
            "--values",
            help="Count the values at the variable positions of the most frequent templates (top values, and "
            "p50/p90/p99 of numbers); runs a second pass, see --values-templates.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = False,
    values_templates: Annotated[
        int,
        typer.Option(
            "--values-templates",
            min=1,
            help="With --values: how many of the most frequent templates get their values counted.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = 200,
    load_state: LoadState = None,
    save_state: SaveState = None,
    state_format: StateForm = "json",
    as_json: AsJson = False,
    source_tail: SourceTail = None,
    source_since: SourceSince = None,
    source_previous: SourcePrevious = False,
    source_timeout: SourceTimeout = DEFAULT_TIMEOUT,
    source_max_mb: SourceMaxMb = DEFAULT_MAX_MB,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Fold FILES into message templates and count them."""
    stack = ExitStack()
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        inputs = open_inputs(
            stack, files, SourceArgs(source_tail, source_since, source_previous, source_timeout, source_max_mb), quiet
        )
        examples_note(settings, masks, masks_file, examples, quiet)
        outputs = resolve_outputs("analysis", out, report, as_json, append)
        threshold = resolve_level(level, only_alerts)
        with progress_reporter(quiet) as progress:
            result = logfold.analyze(
                inputs,
                format=format,
                multiline=multiline,
                since=since,
                until=until,
                examples=examples,  # type: ignore[arg-type]
                values=values,
                value_templates=values_templates,
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
                    on_full,
                    delimiters,
                    masks,
                    masks_file,
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
    finally:
        stack.close()
