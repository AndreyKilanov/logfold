"""The ``logfold formats`` and ``logfold info`` commands."""

from __future__ import annotations

import sys

from rich.markup import escape
from rich.table import Table

import logfold
from logfold.cli.runtime import stdout_console
from logfold.engines import native
from logfold.ext import registry
from logfold.ext.formats import JsonFormat, PlainFormat, RegexFormat


def _describe(spec: PlainFormat | JsonFormat | RegexFormat) -> tuple[str, str]:
    if isinstance(spec, RegexFormat):
        return "regex", spec.pattern
    if isinstance(spec, JsonFormat):
        return "json", f"message: {', '.join(spec.message_keys)}; time: {', '.join(spec.time_keys)}"
    return "plain", "whole line"


def formats() -> None:
    """List the available log formats."""
    console = stdout_console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("name")
    table.add_column("kind")
    table.add_column("details", overflow="fold")
    for name in registry.format_names():
        kind, details = _describe(registry.get_format(name))
        table.add_row(escape(name), kind, escape(details))
    console.print(table)
    console.print(
        "\nUse [bold]regex:<pattern>[/bold] for a custom format. "
        "Named groups message/msg, timestamp/ts/time and level/lvl are picked up."
    )


def info() -> None:
    """Show versions and engine availability (useful in bug reports)."""
    console = stdout_console()
    console.print(f"logfold {logfold.__version__}")
    console.print(f"python {sys.version.split()[0]}")
    versions = native.core_versions()
    if native.is_available() and versions is not None:
        console.print(
            f"native engine: available (core {versions['core']}, contract {versions['contract']}, "
            f"algo {versions['algo']})"
        )
    else:
        console.print("native engine: [yellow]not available[/yellow] (the slow pure-Python engine will be used)")
    console.print(f"formats: {', '.join(registry.format_names())}")
    console.print(f"reporters: {', '.join(registry.reporter_names())}")
