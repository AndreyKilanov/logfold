"""The ``logfold formats`` and ``logfold info`` commands."""

from __future__ import annotations

from rich.markup import escape
from rich.table import Table

import logfold
from logfold.cli.runtime import stdout_console
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
    facts = logfold.info()
    console.print(f"logfold {facts.version}")
    console.print(f"python {facts.python}")
    if facts.native_available:
        console.print(
            f"native engine: available (core {facts.core_version}, contract {facts.contract_version}, "
            f"algo {facts.algo_version})"
        )
    else:
        console.print("native engine: [yellow]not available[/yellow] (the slow pure-Python engine will be used)")
    console.print(f"formats: {', '.join(facts.formats)}")
    console.print(f"reporters: {', '.join(facts.reporters)}")
    console.print(f"matchers: {', '.join(facts.matchers)}")
