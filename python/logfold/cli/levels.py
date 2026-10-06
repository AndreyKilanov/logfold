"""The ``--level`` and ``--only-alerts`` filter: keep templates by their most severe level."""

from __future__ import annotations

import dataclasses
import difflib
from collections.abc import Sequence

from logfold.errors import ConfigError
from logfold.model import LEVEL_NAMES, AnalysisResult, DiffEntry, DiffResult

ALERT_LEVEL = "WARN"
_ALIASES = {"WARNING": "WARN"}


def resolve_level(level: str | None, only_alerts: bool) -> str | None:
    """Turn ``--level`` and ``--only-alerts`` into the lowest level to keep.

    Args:
        level: The ``--level`` value, any case, or ``None``.
        only_alerts: Whether ``--only-alerts`` was given.

    Returns:
        A level name, or ``None`` when nothing is filtered.

    Raises:
        ConfigError: If both options are given or the level is unknown.
    """
    if level is not None and only_alerts:
        raise ConfigError(
            "--level and --only-alerts cannot be combined", hint=f"--only-alerts is --level {ALERT_LEVEL}"
        )
    if only_alerts:
        return ALERT_LEVEL
    if level is None:
        return None
    name = _ALIASES.get(level.upper(), level.upper())
    if name not in LEVEL_NAMES:
        close = difflib.get_close_matches(name, LEVEL_NAMES, n=1)
        raise ConfigError(
            f"unknown level {level!r}; use {', '.join(LEVEL_NAMES)}",
            hint=f"did you mean {close[0]!r}?" if close else None,
        )
    return name


def _keeps(entry_level: str | None, level: str) -> bool:
    return entry_level in LEVEL_NAMES and LEVEL_NAMES.index(entry_level) >= LEVEL_NAMES.index(level)


def _no_levels(format_name: str) -> ConfigError:
    return ConfigError(
        f"cannot filter by level: the {format_name} format gives no levels",
        hint="use a format with levels, or -f regex:<pattern> with a (?P<level>...) group",
    )


def filter_analysis(result: AnalysisResult, level: str) -> AnalysisResult:
    """Keep the templates whose most severe level is at least ``level``.

    Args:
        result: The analysis.
        level: The lowest level to keep.

    Returns:
        The analysis with the other templates dropped; the run counters are unchanged.

    Raises:
        ConfigError: If no template has a level, which means the format has none.
    """
    if result.templates and all(template.level is None for template in result.templates):
        raise _no_levels(result.meta.format)
    kept = tuple(template for template in result.templates if _keeps(template.level, level))
    return dataclasses.replace(result, templates=kept)


def _filter_entries(entries: Sequence[DiffEntry], level: str) -> tuple[DiffEntry, ...]:
    return tuple(entry for entry in entries if _keeps(entry.level, level))


def filter_diff(result: DiffResult, level: str) -> DiffResult:
    """Keep the new, disappeared and changed templates whose most severe level is at least ``level``.

    Args:
        result: The comparison.
        level: The lowest level to keep.

    Returns:
        The comparison with the other entries dropped; ``unchanged`` and the run counters stay as they were.

    Raises:
        ConfigError: If there are entries and none has a level, which means the format has none.
    """
    listed = (*result.new_templates, *result.disappeared, *result.changed)
    if listed and all(entry.level is None for entry in listed):
        raise _no_levels(result.meta.format)
    return dataclasses.replace(
        result,
        new_templates=_filter_entries(result.new_templates, level),
        disappeared=_filter_entries(result.disappeared, level),
        changed=_filter_entries(result.changed, level),
    )


def analysis_note(before: AnalysisResult, after: AnalysisResult, level: str) -> str:
    """Say how many templates the level filter hid.

    Args:
        before: The analysis before filtering.
        after: The analysis after filtering.
        level: The level that was applied.

    Returns:
        A one-line note.
    """
    return f"showing {len(after.templates):,} of {len(before.templates):,} templates at {level} or above"


def diff_note(before: DiffResult, after: DiffResult, level: str) -> str:
    """Say how many entries the level filter hid.

    Args:
        before: The comparison before filtering.
        after: The comparison after filtering.
        level: The level that was applied.

    Returns:
        A one-line note.
    """
    hidden = (
        f"{len(before.new_templates) - len(after.new_templates):,} new, "
        f"{len(before.disappeared) - len(after.disappeared):,} disappeared, "
        f"{len(before.changed) - len(after.changed):,} changed"
    )
    return f"only templates at {level} or above are listed ({hidden} below that were hidden)"
