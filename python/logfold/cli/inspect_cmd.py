"""The ``logfold inspect`` command: how a file is read, without mining it."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.markup import escape
from rich.table import Table
from rich.text import Text

from logfold.api.inspecting import SAMPLE_LINES, SHOWN_RECORDS, Inspection, inspect_file
from logfold.cli.options import PANEL_INPUT, PANEL_OUTPUT, Debug, Format, Multiline
from logfold.cli.output import printable
from logfold.cli.render import level_text
from logfold.cli.runtime import fail, stdout_console
from logfold.errors import ConfigError, LogfoldError

EXAMPLES = """\
Examples:

  logfold inspect app.log

  logfold inspect app.log -f regex:'^(?P<ts>\\S+) (?P<level>\\w+) (?P<message>.*)' -n 20

  logfold inspect app.log --json"""

UNPARSED_HINT_RATIO = 0.10
MESSAGE_WIDTH = 140
KILO = 1024


def _size(value: int) -> str:
    amount = float(value)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if amount < KILO or unit == "GiB":
            return f"{amount:.0f} {unit}" if unit == "B" else f"{amount:.1f} {unit}"
        amount /= KILO
    raise AssertionError("unreachable")


def _message(text: str, lines: int) -> Text:
    first, _, _ = printable(text).partition("\n")
    flat = " ".join(first.split())
    flat = flat if len(flat) <= MESSAGE_WIDTH else flat[: MESSAGE_WIDTH - 1] + "…"
    result = Text(flat)
    if lines > 1:
        result.append(f"  (+{lines - 1} lines)", style="dim")
    return result


def _hints(found: Inspection) -> list[str]:
    hints: list[str] = []
    if found.lines and found.unparsed / found.lines > UNPARSED_HINT_RATIO:
        hints.append(
            f"{found.unparsed} of {found.lines} sampled lines did not parse; try -f plain, -f regex:<pattern> or "
            "--multiline ('logfold formats' lists the formats)"
        )
    if found.records and not found.levels:
        hints.append("the format gives no levels, so --level and --only-alerts have nothing to filter by")
    return hints


def print_inspection(found: Inspection) -> None:
    """Print an inspection as a short summary and a table of the first records.

    Args:
        found: The inspection.
    """
    console = stdout_console()
    detected = f"auto-detected, {found.confidence:.0%} of the sample" if found.confidence is not None else "as given"
    multiline = "on" if found.spec.multiline else "off"
    if found.multiline_auto:
        multiline += " (detected)"
    where = f"{escape(printable(found.path))}  {_size(found.size)}" + ("  gzip" if found.compressed else "")
    console.print(f"[bold]{where}[/bold]", soft_wrap=True)
    console.print(f"format     [cyan]{escape(found.spec.name)}[/cyan] ({detected}); multiline {multiline}")
    more = " (the file continues)" if found.truncated else ""
    console.print(f"sample     {found.lines:,} lines: {found.records:,} records, {found.unparsed:,} unparsed{more}")
    if found.first_time is not None and found.last_time is not None:
        console.print(f"time       {found.first_time.isoformat(sep=' ')} -> {found.last_time.isoformat(sep=' ')}")
    if found.levels:
        counts = " ".join(f"{name} {count:,}" for name, count in list(found.levels.items())[::-1])
        console.print(f"levels     {counts}" + (f" (no level: {found.no_level:,})" if found.no_level else ""))
    if found.shown:
        console.print()
        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("time")
        table.add_column("level")
        table.add_column("message", overflow="fold")
        for record in found.shown:
            moment = record.time.isoformat(sep=" ") if record.time is not None else ""
            table.add_row(moment, level_text(record.level), _message(record.message, record.lines))
        console.print(table)
    for hint in _hints(found):
        console.print(f"[cyan]hint:[/cyan] {escape(hint)}", soft_wrap=True)


def inspection_json(found: Inspection) -> dict[str, Any]:
    """Describe an inspection as a JSON-ready dictionary.

    Args:
        found: The inspection.

    Returns:
        The dictionary, with ``kind`` and ``schema_version`` like the other JSON outputs.
    """

    def stamp(moment: Any) -> str | None:
        return None if moment is None else moment.isoformat()

    return {
        "schema_version": 1,
        "kind": "inspection",
        "path": found.path,
        "size": found.size,
        "compressed": found.compressed,
        "format": found.spec.name,
        "confidence": found.confidence,
        "multiline": found.spec.multiline,
        "multiline_detected": found.multiline_auto,
        "lines": found.lines,
        "records": found.records,
        "unparsed": found.unparsed,
        "truncated": found.truncated,
        "levels": dict(found.levels),
        "no_level": found.no_level,
        "first_time": stamp(found.first_time),
        "last_time": stamp(found.last_time),
        "shown": [
            {"time": stamp(record.time), "level": record.level, "lines": record.lines, "message": record.message}
            for record in found.shown
        ],
    }


def inspect(
    file: Annotated[Path, typer.Argument(help="Log file to look at (gzip is detected by content).")],
    format: Format = "auto",
    multiline: Multiline = None,
    records: Annotated[
        int,
        typer.Option("--records", "-n", min=1, help="Records to show.", rich_help_panel=PANEL_OUTPUT),
    ] = SHOWN_RECORDS,
    sample_lines: Annotated[
        int,
        typer.Option(
            "--sample-lines",
            min=1,
            help="Lines to read for the counts and the time range.",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = SAMPLE_LINES,
    as_json: Annotated[
        bool, typer.Option("--json", help="Print JSON instead of text.", rich_help_panel=PANEL_OUTPUT)
    ] = False,
    debug: Debug = False,
) -> None:
    """Show how a file is read: the detected format and the first records as parsed.

    Only the start of the file is read, so it is quick on any size. Use it to check a format before 'logfold analyze'.
    """
    try:
        if str(file) == "-":
            raise ConfigError(
                "inspect needs a file, not standard input",
                hint="save a sample first, for example: ... | head -n 1000 > sample.log",
            )
        found = inspect_file(file, format=format, multiline=multiline, limit=records, sample_lines=sample_lines)
    except LogfoldError as error:
        raise fail(error, debug) from None
    if as_json:
        text = json.dumps(inspection_json(found), ensure_ascii=False, indent=2) + "\n"
        sys.stdout.write(printable(text) if sys.stdout.isatty() else text)
    else:
        print_inspection(found)
