"""The lines that show the values of the positions of a template, for the text, terminal and HTML reports."""

from __future__ import annotations

from collections.abc import Sequence

from logfold.ext.text import printable
from logfold.model_values import NumericSummary, ValueStats

SHOWN_VALUES = 5
VALUE_WIDTH = 40


def _clip(text: str) -> str:
    flat = " ".join(printable(text).split()) or "(blank)"
    return flat if len(flat) <= VALUE_WIDTH else flat[: VALUE_WIDTH - 1] + "…"


def _number(value: float) -> str:
    return f"{value:,.0f}" if value == int(value) and abs(value) < 1e15 else f"{value:,.4g}"


def _numeric_line(numeric: NumericSummary) -> str:
    return (
        f"numbers ({numeric.count:,}): min {_number(numeric.min)}, p50 {_number(numeric.p50)}, "
        f"p90 {_number(numeric.p90)}, p99 {_number(numeric.p99)}, max {_number(numeric.max)}, "
        f"mean {_number(numeric.mean)}"
    )


def value_lines(values: Sequence[ValueStats]) -> list[str]:
    """Describe the values of the positions of a template in one or two lines for each position.

    Args:
        values: The statistics of the positions, in order.

    Returns:
        The lines, without indentation.
    """
    lines = []
    for item in values:
        distinct = f"{item.distinct:,}{'+' if item.capped else ''} distinct"
        listed = ", ".join(f"{_clip(value)} x{count:,}" for value, count in item.top[:SHOWN_VALUES])
        rest = len(item.top) - SHOWN_VALUES
        tail = f", ... {rest} more listed" if rest > 0 else ""
        lines.append(f"[{item.position}] {printable(item.name)} ({item.count:,} values, {distinct}): {listed}{tail}")
        if item.numeric is not None:
            lines.append(f"      {_numeric_line(item.numeric)}")
    return lines
