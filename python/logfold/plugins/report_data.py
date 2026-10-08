"""The columns of a result for the native renderer of the pipeline reports, and the call.

A reporter sends only the columns it prints. Lists of Python objects are cut to plain lists once here, and the native
renderer does the rest in one call, as the matchers do.
"""

from __future__ import annotations

from collections.abc import Sequence
from operator import attrgetter
from typing import Any

from logfold import _bridge
from logfold.levels import LEVEL_NAMES
from logfold.model import AnalysisResult, DiffEntry, DiffResult, Template

__all__ = ["ALERT_LEVELS", "level_name", "listed_rows", "native_text"]

ALERT_LEVELS = ("WARN", "ERROR", "FATAL")
_LEVELS = frozenset(LEVEL_NAMES)
MIN_LISTED = 1000
"""The native renderer is used when at least this many templates are listed ..."""
LISTED_FRACTION = 8
"""... and the listed templates are at least 1 / this of the templates of the result."""
_LARGEST = 1 << 62
"""Options above this are the same as "everything"; it keeps them inside the integers of the extension."""


def level_name(level: str | None) -> str | None:
    """Return ``level`` when it is a level name, otherwise ``None``.

    A level that does not come from logfold (a hand-edited saved report) is shown as no level, so it carries no markup.
    """
    return level if level in _LEVELS else None


def _column(items: Sequence[Any], attribute: str) -> list[Any]:
    return list(map(attrgetter(attribute), items))


def _template_columns(items: Sequence[Template], fields: frozenset[str]) -> dict[str, Any]:
    columns: dict[str, Any] = {"texts": _column(items, "text"), "after": _column(items, "count")}
    if "ids" in fields:
        columns["ids"] = _column(items, "id")
    if "levels" in fields:
        columns["levels"] = _column(items, "level")
    return columns


def _moments(items: Sequence[DiffEntry], levels: list[str | None]) -> dict[str, list[str]]:
    first = [""] * len(items)
    last = [""] * len(items)
    for index, level in enumerate(levels):
        if level in ALERT_LEVELS:
            entry = items[index]
            first[index] = entry.first_seen.isoformat() if entry.first_seen else ""
            last[index] = entry.last_seen.isoformat() if entry.last_seen else ""
    return {"first": first, "last": last}


def _entry_columns(items: Sequence[DiffEntry], fields: frozenset[str]) -> dict[str, Any]:
    columns: dict[str, Any] = {"texts": _column(items, "text"), "after": _column(items, "after_count")}
    if "ids" in fields:
        columns["ids"] = _column(items, "id")
    levels = _column(items, "level") if {"levels", "moments"} & fields else []
    if "levels" in fields:
        columns["levels"] = levels
    if "before" in fields:
        columns["before"] = _column(items, "before_count")
    if "ratios" in fields:
        columns["ratios"] = _column(items, "ratio")
    if "moments" in fields:
        columns.update(_moments(items, levels))
    return columns


def _data(result: AnalysisResult | DiffResult, fields: frozenset[str], levels: list[tuple[str, int]]) -> dict[str, Any]:
    if isinstance(result, DiffResult):
        before, after = result.before, result.after
        return {
            "kind": "diff",
            "before": {"name": before.name, "records": before.records},
            "after": {"name": after.name, "records": after.records},
            "unchanged": result.unchanged,
            "warnings": list(result.warnings),
            "new": _entry_columns(result.new_templates, fields),
            "changed": _entry_columns(result.changed, fields),
            "disappeared": _entry_columns(result.disappeared, fields),
        }
    return {
        "kind": "analysis",
        "run": {"name": result.run.name, "records": result.run.records, "unparsed": result.run.unparsed},
        "warnings": list(result.warnings),
        "levels": levels,
        "templates": _template_columns(result.templates, fields),
    }


def listed_rows(result: AnalysisResult | DiffResult, top: int) -> tuple[int, int]:
    """Return how many templates a report lists with ``top`` per list, and how many the result has.

    Args:
        result: The result.
        top: The number of templates per list.

    Returns:
        ``(listed, total)``.
    """
    if isinstance(result, DiffResult):
        sizes: tuple[int, ...] = (len(result.new_templates), len(result.changed), len(result.disappeared))
    else:
        sizes = (len(result.templates),)
    return sum(min(top, size) for size in sizes), sum(sizes)


def native_text(
    name: str,
    result: AnalysisResult | DiffResult,
    options: dict[str, int],
    fields: Sequence[str],
    levels: Sequence[tuple[str, int]] = (),
    rows: tuple[int, int] | None = None,
) -> str | None:
    """Render a report in the native engine, or return ``None`` when the caller must render it in Python.

    Args:
        name: Report name.
        result: The result.
        options: Whole-number options of the report (``top`` and a size limit).
        fields: The columns the report prints: ``ids``, ``levels``, ``before``, ``ratios`` and ``moments``.
        levels: For an analysis, the ``(level, records)`` pairs of the report, in the order it wants them.
        rows: ``(listed, total)`` as :func:`listed_rows` returns them. Building the columns costs a pass over every
            template of the result, so the native renderer pays when a good part of the result is listed (measured
            in ``bench/docs/REPORT_PLUGINS.md``); with fewer rows the caller renders in Python, with the same text.

    Returns:
        The text, or ``None`` without a native renderer or for data the extension cannot take (a lone surrogate, a
        count that is negative or above 2^64).

    Raises:
        ConfigError: If the extension rejects the data.
    """
    if not _bridge.supports_reports():
        return None
    if rows is not None and (rows[0] < MIN_LISTED or rows[0] * LISTED_FRACTION < rows[1]):
        return None
    try:
        return _bridge.render_report(
            name, _data(result, frozenset(fields), list(levels)), {k: min(v, _LARGEST) for k, v in options.items()}
        )
    except (UnicodeError, OverflowError):
        return None
