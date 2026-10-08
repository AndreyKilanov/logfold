"""The ``logfold`` command: wires the commands into one Typer app and runs it."""

from __future__ import annotations

import errno
import os
import sys
from pathlib import Path
from typing import Annotated

import typer

import logfold
from logfold.cli import analyze_cmd, diff_cmd, exit_codes, inspect_cmd, match_cmd
from logfold.cli.analyze_cmd import analyze
from logfold.cli.available_help import AvailableHelpCommand
from logfold.cli.diff_cmd import diff
from logfold.cli.info_cmd import formats, info
from logfold.cli.match_cmd import match
from logfold.cli.plugins_cmd import plugins_app
from logfold.cli.runtime import stderr_console
from logfold.errors import LogfoldError
from logfold.ext import registry
from logfold.settings import Settings

app = typer.Typer(
    name="logfold",
    help="Fold large logs into templates and compare two runs.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
app.add_typer(plugins_app, name="plugins")


def _version(value: bool) -> None:
    if value:
        typer.echo(f"logfold {logfold.__version__}")
        raise typer.Exit()


@app.callback()
def root(
    ctx: typer.Context,
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version.")
    ] = False,
    plugins_dir: Annotated[
        list[Path] | None,
        typer.Option("--plugins-dir", help="Also load plugins from this folder (repeatable)."),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option(
            "--config",
            metavar="FILE",
            help="Read the settings from this logfold.toml; without it the first logfold.toml from the current folder "
            "up to the repository root is used (LOGFOLD_CONFIG names one too).",
        ),
    ] = None,
    no_config: Annotated[bool, typer.Option("--no-config", help="Do not read any logfold.toml.")] = False,
) -> None:
    """Fold large logs into templates and compare two runs."""
    for folder in plugins_dir or ():
        registry.add_plugin_directory(folder)
    try:
        if config is not None and no_config:
            raise logfold.ConfigError("--config and --no-config exclude each other")
        settings = Settings() if no_config else logfold.load_config(config)
    except LogfoldError as error:
        ctx.obj = error
        return
    ctx.obj = settings
    ctx.default_map = settings.command_defaults()


app.command(cls=AvailableHelpCommand, epilog=analyze_cmd.EXAMPLES)(analyze)
app.command(cls=AvailableHelpCommand, epilog=match_cmd.EXAMPLES)(match)
app.command(cls=AvailableHelpCommand, epilog=diff_cmd.EXAMPLES)(diff)
app.command(cls=AvailableHelpCommand, epilog=inspect_cmd.EXAMPLES)(inspect_cmd.inspect)
app.command()(formats)
app.command()(info)


CLOSED_PIPE_ERRNOS = frozenset({errno.EPIPE, errno.EINVAL})
"""Errors of a write to a pipe whose reader has gone; Windows reports ``EINVAL`` instead of ``EPIPE``."""


def _is_closed_pipe(error: OSError) -> bool:
    return error.errno in CLOSED_PIPE_ERRNOS and not sys.stdout.isatty()


def _silence_stdout() -> None:
    """Point standard output at the null device so the final flush at interpreter exit cannot fail again."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


def run() -> None:
    """Run the app with UTF-8 safe output streams.

    A reader that closes the pipe early (``logfold info | head``) ends the command quietly with the error exit code.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    try:
        app()
    except KeyboardInterrupt:
        stderr_console().print("interrupted", highlight=False)
        raise SystemExit(exit_codes.INTERRUPTED) from None
    except OSError as error:
        if not _is_closed_pipe(error):
            raise
        _silence_stdout()
        raise SystemExit(exit_codes.ERROR) from None
