"""The ``logfold learn`` command: save a model for ``logfold check``."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Annotated

import typer

import logfold
from logfold.api.fetch import DEFAULT_TIMEOUT
from logfold.cli.options import (
    PANEL_INPUT,
    ChunkMb,
    Debug,
    Delimiters,
    Depth,
    Engine,
    Format,
    HighCardinality,
    Masks,
    MasksFile,
    MaxChildren,
    MaxTemplates,
    Multiline,
    NoMasks,
    OnFull,
    Quiet,
    SimTh,
    Since,
    StateForm,
    Strategy,
    Threads,
    Until,
    WarmStart,
    mining_options,
)
from logfold.cli.runtime import config_note, fail, note, progress_reporter, settings_of
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

  logfold learn good.log --state model.json

  logfold learn release-1.log release-2.log --state model.json --masks secrets,pii

  logfold check app.log --state model.json"""


def learn(
    ctx: typer.Context,
    files: Annotated[list[str], typer.Argument(help=INPUT_HELP)],
    state: Annotated[
        Path,
        typer.Option(
            "--state",
            metavar="MODEL",
            help="Where to save the model; a .gz path is compressed. 'logfold check --state' reads it.",
            rich_help_panel=PANEL_INPUT,
        ),
    ],
    format: Format = "auto",
    multiline: Multiline = None,
    since: Since = None,
    until: Until = None,
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
    state_format: StateForm = "json",
    source_tail: SourceTail = None,
    source_since: SourceSince = None,
    source_previous: SourcePrevious = False,
    source_timeout: SourceTimeout = DEFAULT_TIMEOUT,
    source_max_mb: SourceMaxMb = DEFAULT_MAX_MB,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Learn the templates of FILES and save them as a model for 'logfold check' (same as 'analyze --save-state')."""
    stack = ExitStack()
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        inputs = open_inputs(
            stack, files, SourceArgs(source_tail, source_since, source_previous, source_timeout, source_max_mb), quiet
        )
        with progress_reporter(quiet) as progress:
            result = logfold.analyze(
                inputs,
                format=format,
                multiline=multiline,
                since=since,
                until=until,
                examples="none",
                save_state=state,
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
        note(
            f"saved the model to {printable(str(state))}: {len(result.templates):,} templates from "
            f"{result.run.records:,} records",
            quiet,
        )
    except LogfoldError as error:
        raise fail(error, debug) from None
    finally:
        stack.close()
