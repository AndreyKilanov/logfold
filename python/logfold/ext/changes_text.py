"""The lines that show the new and gone values of a comparison, for the text, terminal, HTML and Markdown reports."""

from __future__ import annotations

from collections.abc import Sequence

from logfold.ext.text import printable
from logfold.model_values import TemplateValueChanges, ValueChange

SHOWN_VALUES = 5
VALUE_WIDTH = 40
NOT_COMPARED = "not compared: more different values than the memory limit allows"


def _clip(text: str) -> str:
    flat = " ".join(printable(text).split()) or "(blank)"
    return flat if len(flat) <= VALUE_WIDTH else flat[: VALUE_WIDTH - 1] + "…"


def _values(label: str, values: tuple[tuple[str, int], ...], distinct: int) -> str:
    listed = ", ".join(f"{_clip(value)} x{count:,}" for value, count in values[:SHOWN_VALUES])
    rest = distinct - min(len(values), SHOWN_VALUES)
    tail = f", ... {rest:,} more" if listed and rest > 0 else ""
    return f"{label}{listed}{tail}" if listed else ""


def change_lines(change: ValueChange) -> list[str]:
    """Describe the new and gone values of one position in a few lines.

    Args:
        change: What differs at the position.

    Returns:
        The lines, without indentation: the counts, then the new values and the gone ones when there are any to show.
    """
    if change.capped:
        before = f"{change.before_distinct:,}+"
        after = f"{change.after_distinct:,}+"
        return [
            f"[{change.position}] {printable(change.name)}: {NOT_COMPARED} (counted: {before} before, {after} after)"
        ]
    head = (
        f"[{change.position}] {printable(change.name)}: {change.new_distinct:,} new, {change.gone_distinct:,} gone, "
        f"{change.shared_distinct:,} in both ({change.before_distinct:,} before, {change.after_distinct:,} after)"
    )
    lines = [head]
    for line in (
        _values("      new:  ", change.new, change.new_distinct),
        _values("      gone: ", change.gone, change.gone_distinct),
    ):
        if line:
            lines.append(line)
    return lines


def changes_lines(changes: Sequence[TemplateValueChanges], top: int) -> list[str]:
    """Describe the templates whose values differ, as the section of a text report.

    Args:
        changes: The templates, from :attr:`logfold.DiffResult.value_changes`.
        top: How many templates to show.

    Returns:
        The lines of the section, starting with an empty one.
    """
    lines = ["", f"Values that differ ({len(changes):,} templates)"]
    if not changes:
        return [*lines, "  none"]
    for item in changes[:top]:
        level = f"  [{item.level}]" if item.level else ""
        lines.append(f"  {printable(item.text)}{level}")
        for change in item.changes:
            lines.extend(f"    {line}" for line in change_lines(change))
    if len(changes) > top:
        lines.append(f"... {len(changes) - top:,} more")
    return lines
