"""Rich rendering of results for terminals."""

from __future__ import annotations

import re
from collections.abc import Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from logfold.model import AnalysisResult, DiffEntry, DiffResult

_VARIABLE = re.compile(r"(<[A-Z]+>|<\*>)")
_LEVEL_STYLE = {"WARN": "yellow", "ERROR": "red", "FATAL": "bold red"}


def _template_text(text: str, limit: int = 160) -> Text:
    flat = " ".join(text.split())
    flat = flat if len(flat) <= limit else flat[: limit - 1] + "…"
    result = Text()
    for index, part in enumerate(_VARIABLE.split(flat)):
        result.append(part, style="orange3" if index % 2 else "")
    return result


def _level(level: str | None) -> Text:
    return Text(level or "", style=_LEVEL_STYLE.get(level or "", "dim"))


def print_analysis(console: Console, result: AnalysisResult, top: int) -> None:
    """Print a summary line and a table of the most frequent templates.

    Args:
        console: Target console.
        result: Analysis result.
        top: Number of templates to show.
    """
    run = result.run
    console.print(
        f"[bold]{run.name}[/bold]: {run.records:,} records, {len(result.templates):,} templates, "
        f"{run.unparsed:,} unparsed lines, format [cyan]{result.meta.format}[/cyan], "
        f"{result.metrics.engine} engine, {result.metrics.wall_total_s:.2f}s",
        highlight=False,
    )
    for warning in result.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}", highlight=False)
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("count", justify="right")
    table.add_column("share", justify="right")
    table.add_column("level")
    table.add_column("template", overflow="fold")
    for template in result.top(top):
        share = template.count / run.records if run.records else 0.0
        table.add_row(f"{template.count:,}", f"{share:.2%}", _level(template.level), _template_text(template.text))
    console.print(table)
    hidden = len(result.templates) - top
    if hidden > 0:
        console.print(f"[dim]... {hidden:,} more templates (use --top or --out)[/dim]")


def _entries_table(title: str, entries: Sequence[DiffEntry], top: int, console: Console, style: str) -> None:
    console.print(f"\n[bold {style}]{title}[/bold {style}] ({len(entries):,})", highlight=False)
    if not entries:
        console.print("[dim]none[/dim]")
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("before", justify="right")
    table.add_column("after", justify="right")
    table.add_column("change", justify="right")
    table.add_column("level")
    table.add_column("template", overflow="fold")
    for entry in entries[:top]:
        change = f"x{entry.ratio:.2f}" if entry.ratio is not None else ("new" if entry.before_count == 0 else "gone")
        table.add_row(
            f"{entry.before_count:,}",
            f"{entry.after_count:,}",
            change,
            _level(entry.level),
            _template_text(entry.text),
        )
    console.print(table)
    if len(entries) > top:
        console.print(f"[dim]... {len(entries) - top:,} more[/dim]")


def print_diff(console: Console, result: DiffResult, top: int) -> None:
    """Print a summary line and tables of new, changed and disappeared templates.

    Args:
        console: Target console.
        result: Diff result.
        top: Rows per table.
    """
    console.print(
        f"[bold]{result.before.name}[/bold] -> [bold]{result.after.name}[/bold]: "
        f"{result.before.records:,} -> {result.after.records:,} records, "
        f"[green]{len(result.new_templates):,} new[/green] ([red]{len(result.new_alerts):,} WARN+[/red]), "
        f"[yellow]{len(result.disappeared):,} disappeared[/yellow], "
        f"[magenta]{len(result.changed):,} changed[/magenta], {result.unchanged:,} unchanged, "
        f"{result.metrics.engine} engine, {result.metrics.wall_total_s:.2f}s",
        highlight=False,
    )
    for warning in result.warnings:
        console.print(f"[yellow]warning:[/yellow] {warning}", highlight=False)
    _entries_table("New templates", result.new_templates, top, console, "green")
    _entries_table("Changed templates", result.changed, top, console, "magenta")
    _entries_table("Disappeared templates", result.disappeared, top, console, "yellow")
