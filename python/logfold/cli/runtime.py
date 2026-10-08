"""Consoles, progress, error reporting and result output shared by the commands."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import (
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TransferSpeedColumn,
)

from logfold.cli import exit_codes
from logfold.cli.hints import hint_for
from logfold.cli.output import render_report
from logfold.cli.render import print_analysis, print_diff
from logfold.errors import LogfoldError, write_error
from logfold.ext.files import write_text
from logfold.ext.text import printable
from logfold.model import AnalysisResult, DiffResult
from logfold.settings import Settings


def stdout_console() -> Console:
    """Return a console writing to standard output."""
    return Console(file=sys.stdout, highlight=False)


def stderr_console() -> Console:
    """Return a console writing to standard error."""
    return Console(file=sys.stderr, highlight=False)


@contextmanager
def progress_reporter(quiet: bool) -> Iterator[Callable[[int], None] | None]:
    """Show a progress spinner on a terminal; yield the callback that advances it, or ``None`` when it is off.

    Args:
        quiet: Whether ``--quiet`` was given.

    Yields:
        A callback taking the number of bytes consumed since the last call, or ``None`` for quiet runs and when
        standard error is not a terminal.
    """
    if quiet or not sys.stderr.isatty():
        yield None
        return
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeElapsedColumn(),
        console=stderr_console(),
        transient=True,
    ) as progress:
        task = progress.add_task("reading", total=None)
        yield lambda consumed: progress.advance(task, consumed)


def fail(error: Exception, debug: bool) -> typer.Exit:
    """Print an error with the next step, if any, and build the exit that ends the command.

    With ``--debug`` the error is re-raised instead, to show the traceback. Paths are not wrapped at the terminal
    width, and markup or control characters in the text are shown literally.

    Args:
        error: The error to report.
        debug: Whether ``--debug`` was given.

    Returns:
        The exception to raise with the error exit code.

    Raises:
        Exception: ``error`` itself when ``debug`` is set.
    """
    if debug:
        raise error
    console = stderr_console()
    console.print(f"[red]error:[/red] {escape(printable(str(error)))}", soft_wrap=True)
    hint = hint_for(error)
    if hint:
        console.print(f"[cyan]hint:[/cyan] {escape(printable(hint))}", soft_wrap=True)
    return typer.Exit(exit_codes.ERROR)


def settings_of(ctx: typer.Context) -> Settings:
    """Return the settings that the root command loaded for this run.

    Args:
        ctx: The context of a command.

    Returns:
        The settings of ``logfold.toml``, or the built-in defaults when none is used.

    Raises:
        LogfoldError: The error that reading the settings file raised; it is kept until a command needs the settings,
            so that ``--help`` works whatever the file holds.
    """
    if isinstance(ctx.obj, LogfoldError):
        raise ctx.obj
    return ctx.obj if isinstance(ctx.obj, Settings) else Settings()


def config_note(settings: Settings, quiet: bool) -> None:
    """Say on standard error which settings file the run uses, unless quiet."""
    if settings.source is not None:
        note(f"config: {printable(settings.source)}", quiet)


def given_on_command_line(ctx: typer.Context, name: str) -> bool:
    """Tell whether the user typed the option ``name`` (and it did not come from the settings file or a default)."""
    source = ctx.get_parameter_source(name)
    return source is not None and source.name == "COMMANDLINE"


def note(message: str, quiet: bool) -> None:
    """Print a one-line note on standard error unless quiet.

    Args:
        message: The note.
        quiet: Whether ``--quiet`` was given.
    """
    if not quiet:
        stderr_console().print(f"[dim]{escape(message)}[/dim]", soft_wrap=True)


def write_report(
    result: AnalysisResult | DiffResult, out: Path, reporter: str, quiet: bool, append: bool = False
) -> None:
    """Write a report file and say so on standard error unless quiet.

    Args:
        result: The result to render.
        out: Target file.
        reporter: Reporter name.
        quiet: Whether ``--quiet`` was given.
        append: Add to the end of the file instead of replacing it.
    """
    text = render_report(result, reporter)
    try:
        write_text(out, text, append)
    except OSError as error:
        raise write_error(str(out), error) from error
    if not quiet:
        opener = "  (open it in a browser)" if out.suffix.lower() in (".html", ".htm") else ""
        verb = "appended to" if append else "wrote"
        stderr_console().print(f"{verb} {escape(printable(str(out)))}{opener}", highlight=False, soft_wrap=True)


def write_stdout(text: str) -> None:
    """Write report text to standard output; into a pipe or a file the line breaks stay line feeds on Windows too.

    Args:
        text: The text to write.
    """
    stream = sys.stdout
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None and not stream.isatty():
        reconfigure(newline="\n")
    stream.write(text)


def emit(result: AnalysisResult | DiffResult, top: int, reporter: str | None) -> None:
    """Print a result to standard output: a reporter's text, rich tables on a terminal or plain text otherwise.

    Args:
        result: The result to print.
        top: Rows per table.
        reporter: Reporter whose text replaces the tables, or ``None``.
    """
    if reporter is not None:
        text = render_report(result, reporter, top)
        write_stdout(printable(text) if sys.stdout.isatty() else text)
        return
    if sys.stdout.isatty():
        console = stdout_console()
        if isinstance(result, DiffResult):
            print_diff(console, result, top)
        else:
            print_analysis(console, result, top)
        return
    write_stdout(result.render("text", top=top))
