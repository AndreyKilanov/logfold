"""The ``logfold formats`` and ``logfold info`` commands."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.table import Table

import logfold
from logfold.cli.runtime import stdout_console
from logfold.errors import LogfoldError
from logfold.ext import printable, registry
from logfold.ext.formats import JsonFormat, PlainFormat, RegexFormat


def _describe(spec: PlainFormat | JsonFormat | RegexFormat) -> tuple[str, str]:
    if isinstance(spec, RegexFormat):
        return "regex", spec.pattern
    if isinstance(spec, JsonFormat):
        return "json", f"message: {', '.join(spec.message_keys)}; time: {', '.join(spec.time_keys)}"
    return "plain", "whole line"


def _print_available(console: Console) -> None:
    """Show the catalog's format plugins that are not installed; says nothing if there are none or the catalog fails."""
    from logfold.plugins import listing  # noqa: PLC0415 - slow imports

    try:
        rows = listing.list_plugins(kind="format", status="available")
    except (LogfoldError, OSError):
        return
    if not rows:
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("name")
    table.add_column("details", overflow="fold")
    for row in rows:
        how = row.install if row.compatible else f"needs logfold {row.min_logfold} or newer"
        details = f"{row.description} " if row.description else ""
        table.add_row(escape(printable(row.name)), escape(printable(f"{details}[{how}]")))
    console.print("\n[bold]Available from the plugin catalog[/bold] (not installed):")
    console.print(table)


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
    _print_available(console)
    console.print(
        "\nUse [bold]regex:<pattern>[/bold] or [bold]log4j:<pattern>[/bold] for a custom format. "
        "Named groups message/msg, timestamp/ts/time and level/lvl are picked up."
    )


def info() -> None:
    """Show versions and engine availability (useful in bug reports)."""
    console = stdout_console()
    facts = logfold.info()
    console.print(f"logfold {facts.version}")
    console.print(f"python {facts.python}")
    if facts.native_available:
        console.print(
            f"native engine: available (core {facts.core_version}, contract {facts.contract_version}, "
            f"algo {facts.algo_version})"
        )
    else:
        console.print(
            "native engine: [yellow]not available[/yellow] (install a wheel for this platform: mining needs it)"
        )
    console.print(f"formats: {', '.join(facts.formats)}")
    console.print(f"reporters: {', '.join(facts.reporters)}")
    console.print(f"matchers: {', '.join(facts.matchers)}")
