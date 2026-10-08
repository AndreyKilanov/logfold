"""Time windows: the ``since``, ``until`` and ``split_at`` options of ``analyze()`` and ``diff()``.

A window keeps the records whose timestamp is at or after ``since`` and before ``until``. Times are ISO 8601 strings or
``datetime`` objects; one with a zone is converted to UTC, one without is compared with the times of the log as they
are written (the engines take a log time without a zone as UTC, the same way they do everywhere else).
"""

from __future__ import annotations

import dataclasses
from datetime import datetime

from logfold.errors import ConfigError
from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.model import RunSummary, datetime_to_micros, micros_to_datetime

__all__ = [
    "OPEN",
    "TimeBound",
    "Window",
    "has_time",
    "labeled",
    "require_time",
    "split_windows",
    "to_micros",
    "window",
    "window_warnings",
]

TimeBound = datetime | str | None
Window = tuple[int | None, int | None]
OPEN: Window = (None, None)


def to_micros(value: TimeBound, name: str) -> int | None:
    """Convert a time bound to microseconds since the Unix epoch.

    Args:
        value: A ``datetime``, an ISO 8601 string (``2026-10-06``, ``2026-10-06T12:30:00``,
            ``2026-10-06 12:30:00+03:00``; a trailing ``Z`` means UTC), or ``None`` for no bound.
        name: Option name for error messages.

    Returns:
        Microseconds, or ``None`` when there is no bound.

    Raises:
        ConfigError: If a string is not an ISO 8601 time.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return datetime_to_micros(value)
    if not isinstance(value, str):
        raise ConfigError(f"{name} must be a datetime or an ISO 8601 string, got {type(value).__name__}")
    text = value.strip()
    if text[-1:] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime_to_micros(datetime.fromisoformat(text))
    except ValueError:
        raise ConfigError(
            f"{name} must be an ISO 8601 time such as 2026-10-06T12:30:00, got {value!r}",
            hint="a time with a zone looks like 2026-10-06T12:30:00+03:00 or ends with Z",
        ) from None


def window(since: TimeBound, until: TimeBound) -> Window:
    """Build a window from two bounds.

    Args:
        since: First admitted time, or ``None``.
        until: First time that is no longer admitted, or ``None``.

    Returns:
        ``(since, until)`` in microseconds.

    Raises:
        ConfigError: If a bound cannot be read or ``since`` is not before ``until``.
    """
    start, end = to_micros(since, "since"), to_micros(until, "until")
    if start is not None and end is not None and start >= end:
        raise ConfigError("since must be before until")
    return start, end


def split_windows(since: TimeBound, until: TimeBound, split_at: TimeBound) -> tuple[Window, Window]:
    """Build the windows of the two runs of a comparison of one log cut at ``split_at``.

    Args:
        since: Start of the first run, or ``None``.
        until: End of the second run, or ``None``.
        split_at: The cut: the first run ends here, the second starts here.

    Returns:
        The window of the first and of the second run.

    Raises:
        ConfigError: If a time cannot be read or they are not in the order ``since < split_at < until``.
    """
    cut = to_micros(split_at, "split_at")
    if cut is None:
        raise ConfigError("split_at needs a time")
    return window(since, split_at), window(split_at, until)


def has_time(spec: FormatSpec | Format) -> bool:
    """Tell whether a format reads a timestamp, so that a time window can be applied to it.

    Args:
        spec: A format specification.

    Returns:
        ``False`` for a format that never produces a timestamp.
    """
    if isinstance(spec, PlainFormat):
        return False
    if isinstance(spec, RegexFormat):
        return spec.time_group is not None
    if isinstance(spec, JsonFormat):
        return bool(spec.time_keys)
    return True


def require_time(spec: FormatSpec | Format) -> None:
    """Refuse a time window for a format that never produces a timestamp.

    Args:
        spec: The format that will read the log.

    Raises:
        ConfigError: If the format has no timestamp.
    """
    if not has_time(spec):
        raise ConfigError(
            "this format has no timestamp, so a time window cannot be applied",
            hint="use a format that reads the time, for example one of 'logfold formats' or a regex with a time group",
        )


def _bound(micros: int | None) -> str:
    moment = micros_to_datetime(micros, tz_aware=False)
    return "..." if moment is None else moment.isoformat(timespec="seconds")


def labeled(summary: RunSummary, bounds: Window) -> RunSummary:
    """Show the time window in the name of a run, as ``app.log [since, until)``.

    Args:
        summary: The run.
        bounds: Its window.

    Returns:
        The run with a longer name, or the run itself when the window is open. A bound is shown as the wall-clock time
        the engines compared (a time with a zone has been converted to UTC); an open bound is ``...``.
    """
    if bounds == OPEN:
        return summary
    return dataclasses.replace(summary, name=f"{summary.name} [{_bound(bounds[0])}, {_bound(bounds[1])})")


def window_warnings(summary: RunSummary) -> list[str]:
    """Say what a time window left out of a run, when it left out records without a timestamp.

    Args:
        summary: The run.

    Returns:
        Zero or one sentence.
    """
    if not summary.untimed:
        return []
    return [
        f"{summary.name}: {summary.untimed:,} records without a usable timestamp were left out because a time window "
        "was set"
    ]
