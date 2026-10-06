"""The ``--level`` and ``--only-alerts`` options: which level to keep, and the note about what was hidden."""

from __future__ import annotations

from logfold.errors import ConfigError
from logfold.levels import normalize_level
from logfold.model import AnalysisResult, DiffResult

ALERT_LEVEL = "WARN"


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
    return None if level is None else normalize_level(level)


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
