"""The ``logfold stream`` command: mine a log while it is written and print each template when it first appears."""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated, BinaryIO

import typer

import logfold
from logfold.cli import exit_codes
from logfold.cli.follow import Backlog, read_lines
from logfold.cli.levels import analysis_note, resolve_level
from logfold.cli.options import (
    PANEL_INPUT,
    PANEL_OUTPUT,
    Append,
    AsJson,
    Debug,
    Depth,
    Examples,
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
    StateForm,
    Top,
)
from logfold.cli.output import resolve_outputs
from logfold.cli.runtime import config_note, emit, fail, note, settings_of, write_report, write_stdout
from logfold.errors import ConfigError, LogfoldError, read_error
from logfold.ext.text import printable

EXAMPLES = """Examples:

  kubectl logs -f deploy/api | logfold stream --format plain

  tail -F app.log | logfold stream -f app --save-state model.json --save-every 60

  logfold stream app.log --load-state model.json --json > result.json"""

IDLE_SECONDS = 1.0


def _announcer(enabled: bool) -> Callable[[list[str]], None]:
    def announce(texts: list[str]) -> None:
        if not enabled or not texts:
            return
        write_stdout("".join(f"new  {printable(' '.join(text.split()))}\n" for text in texts))
        sys.stdout.flush()

    return announce


def _follow(
    miner: logfold.Miner,
    backlog: Backlog,
    batch_size: int,
    announce: Callable[[list[str]], None],
    save: Callable[[], None] | None,
    save_every: float | None,
    label: str,
) -> bool:
    """Feed the miner until the stream ends or the user interrupts; return True when it was interrupted."""
    last_save = time.monotonic()
    try:
        while True:
            try:
                lines, finished = backlog.take(batch_size, IDLE_SECONDS)
            except OSError as error:
                raise read_error(label, error) from error
            if lines:
                miner.add_lines(lines)
            elif not finished:
                miner.flush()
            announce(miner.new_templates())
            if finished:
                break
            if save is not None and save_every is not None and time.monotonic() - last_save >= save_every:
                save()
                last_save = time.monotonic()
    except KeyboardInterrupt:
        backlog.stop()
        return True
    finally:
        miner.flush()
        announce(miner.new_templates())
    return False


def stream(
    ctx: typer.Context,
    file: Annotated[
        Path | None,
        typer.Argument(help="Log file to read; '-' or nothing reads standard input.", rich_help_panel=PANEL_INPUT),
    ] = None,
    format: Annotated[
        str,
        typer.Option(
            "--format",
            "-f",
            help="A name from 'logfold formats', regex:<pattern> or log4j:<pattern>; auto is not available.",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = "plain",
    multiline: Multiline = None,
    top: Top = 20,
    level: Level = None,
    only_alerts: OnlyAlerts = False,
    out: Out = None,
    append: Append = False,
    report: Report = None,
    sim_th: SimTh = None,
    depth: Depth = None,
    max_children: MaxChildren = None,
    max_templates: MaxTemplates = None,
    no_masks: NoMasks = False,
    examples: Examples = "raw",
    load_state: LoadState = None,
    save_state: SaveState = None,
    state_format: StateForm = "json",
    save_every: Annotated[
        float | None,
        typer.Option(
            "--save-every",
            min=1.0,
            metavar="SECONDS",
            help="Also write --save-state every SECONDS while the stream runs, not only at the end.",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = None,
    batch_size: Annotated[
        int,
        typer.Option(
            "--batch-size",
            min=1,
            help="Most lines mined in one step; a quiet stream is mined after a second.",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = 1000,
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Mine a log as it is written: print each new template, then report what was read when the input ends.

    Ctrl+C ends the input too: the state is saved and the report is written for what was read so far. 'auto' cannot
    be used as the format, because a stream has no file to detect it from.
    """
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        outputs = resolve_outputs("analysis", out, report, as_json, append)
        threshold = resolve_level(level, only_alerts)
        if save_every is not None and save_state is None:
            raise ConfigError("--save-every needs --save-state")
        miner = logfold.Miner(
            format=format,
            multiline=multiline,
            depth=depth,
            sim_th=sim_th,
            max_children=max_children,
            max_templates=max_templates,
            masks=[] if no_masks else None,
            load_state=load_state,
            state_format=state_format,
            examples=examples,  # type: ignore[arg-type]
            config=settings,
        )
        label = "standard input" if file is None or str(file) == "-" else str(file)
        source: BinaryIO = sys.stdin.buffer
        if file is not None and str(file) != "-":
            try:
                source = file.open("rb")
            except OSError as error:
                raise read_error(label, error) from error
        backlog = Backlog()
        threading.Thread(target=read_lines, args=(source, backlog), daemon=True).start()

        saver = None if save_state is None else partial(miner.save_state, save_state)
        interrupted = _follow(miner, backlog, batch_size, _announcer(outputs.stdout is None), saver, save_every, label)
        if save_state is not None and saver is not None:
            saver()
            note(f"saved the state to {printable(str(save_state))}", quiet)
        if interrupted:
            note("stopped by Ctrl+C; the report is for what was read so far", quiet)
        result = miner.result()
        shown = result if threshold is None else result.filter(min_level=threshold)
        if threshold is not None:
            note(analysis_note(result, shown, threshold), quiet)
        emit(shown, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(result if outputs.file == "json" else shown, out, outputs.file, quiet, append)
        if interrupted:
            raise typer.Exit(exit_codes.INTERRUPTED)
    except LogfoldError as error:
        raise fail(error, debug) from None
