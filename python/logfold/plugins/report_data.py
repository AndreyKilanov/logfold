"""The columns of a result for the native renderer of the pipeline reports, and the call.

A reporter sends only the columns it prints. Lists of Python objects are cut to plain lists once here, and the native
renderer does the rest in one call.
"""

from __future__ import annotations

from collections.abc import Sequence
from operator import attrgetter
from typing import Any

from logfold import _bridge
from logfold.levels import LEVEL_NAMES
from logfold.model import AnalysisResult, DiffEntry, DiffResult, Template

__all__ = ["int_option", "render_native"]

ALERT_LEVELS = ("WARN", "ERROR", "FATAL")
_LEVELS = frozenset(LEVEL_NAMES)
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


def render_native(
    name: str,
    result: AnalysisResult | DiffResult,
    options: dict[str, int],
    fields: Sequence[str],
    levels: Sequence[tuple[str, int]] = (),
) -> str:
    """Render a report in the native engine.

    Args:
        name: Report name.
        result: The result.
        options: Whole-number options of the report (``top`` and a size limit).
        fields: The columns the report prints: ``ids``, ``levels``, ``before``, ``ratios`` and ``moments``.
        levels: For an analysis, the ``(level, records)`` pairs of the report, in the order it wants them.

    Returns:
        The text of the report.

    Raises:
        EngineError: If the native extension is unavailable.
        ConfigError: If the extension rejects the data, or a count of the result is negative or above 2^64 - 1.
    """
    data = _data(result, frozenset(fields), list(levels))
    return _bridge.render_report(name, data, {key: min(value, _LARGEST) for key, value in options.items()})


def int_option(options: dict[str, object], name: str, default: int, *, minimum: int = 1) -> int:
    """Read a whole-number reporter option, falling back to the default for anything else.

    Args:
        options: The keyword options given to ``render``.
        name: Option name.
        default: Value used when the option is missing, not an integer or below ``minimum``.
        minimum: Smallest accepted value.

    Returns:
        The option value or the default.
    """
    value = options.get(name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= minimum else default
