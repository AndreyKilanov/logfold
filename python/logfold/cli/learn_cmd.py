"""The ``logfold learn`` command: save a model for ``logfold check``."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

import logfold
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
from logfold.errors import LogfoldError
from logfold.ext.text import printable

EXAMPLES = """Examples:

  logfold learn good.log --state model.json

  logfold learn release-1.log release-2.log --state model.json --masks secrets,pii

  logfold check app.log --state model.json"""


def learn(
    ctx: typer.Context,
    files: Annotated[list[Path], typer.Argument(help="Log files of the good run ('-' reads standard input).")],
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
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Learn the templates of FILES and save them as a model for 'logfold check' (same as 'analyze --save-state')."""
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        with progress_reporter(quiet) as progress:
            result = logfold.analyze(
                [str(f) for f in files],
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
