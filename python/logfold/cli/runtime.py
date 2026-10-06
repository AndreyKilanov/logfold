"""Consoles, progress, error reporting and result output shared by the commands."""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from logfold.cli import exit_codes
from logfold.cli.hints import hint_for
from logfold.cli.output import printable, render_report
from logfold.cli.render import print_analysis, print_diff
from logfold.model import AnalysisResult, DiffResult


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


def write_report(result: AnalysisResult | DiffResult, out: Path, reporter: str, quiet: bool) -> None:
    """Write a report file and say so on standard error unless quiet.

    Args:
        result: The result to render.
        out: Target file.
        reporter: Reporter name.
        quiet: Whether ``--quiet`` was given.
    """
    out.write_text(render_report(result, reporter), encoding="utf-8")
    if not quiet:
        stderr_console().print(f"wrote {out}", highlight=False)


def emit(result: AnalysisResult | DiffResult, top: int, reporter: str | None) -> None:
    """Print a result to standard output: a reporter's text, rich tables on a terminal or plain text otherwise.

    Args:
        result: The result to print.
        top: Rows per table.
        reporter: Reporter whose text replaces the tables, or ``None``.
    """
    if reporter is not None:
        text = render_report(result, reporter, top)
        sys.stdout.write(printable(text) if sys.stdout.isatty() else text)
        return
    if sys.stdout.isatty():
        console = stdout_console()
        if isinstance(result, DiffResult):
            print_diff(console, result, top)
        else:
            print_analysis(console, result, top)
        return
    sys.stdout.write(result.render("text", top=top))
