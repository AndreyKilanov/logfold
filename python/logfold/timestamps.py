"""Conversion between microseconds since the Unix epoch and ``datetime`` values, the time form of the result model."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def micros_to_datetime(micros: int | None, tz_aware: bool) -> datetime | None:
    """Convert microseconds since the Unix epoch to a ``datetime``.

    Args:
        micros: Microseconds, or ``None``.
        tz_aware: Return an aware UTC datetime when true, otherwise a naive one holding the same wall-clock time.

    Returns:
        The datetime, or ``None`` when ``micros`` is ``None``.
    """
    if micros is None:
        return None
    moment = _EPOCH + timedelta(microseconds=micros)
    return moment if tz_aware else moment.replace(tzinfo=None)


def micros_to_datetimes(values: Sequence[int | None], tz_aware: bool) -> list[datetime | None]:
    """Convert a column of microsecond timestamps; the column form of :func:`micros_to_datetime`.

    Args:
        values: Microseconds since the Unix epoch, or ``None``.
        tz_aware: Return aware UTC datetimes when true, otherwise naive ones holding the same wall-clock time.

    Returns:
        The datetimes, ``None`` where the value is ``None``.
    """
    epoch = _EPOCH if tz_aware else _EPOCH.replace(tzinfo=None)
    return [None if value is None else epoch + timedelta(microseconds=value) for value in values]


def datetime_to_micros(moment: datetime | None) -> int | None:
    """Convert a ``datetime`` to microseconds since the Unix epoch; the inverse of :func:`micros_to_datetime`.

    Args:
        moment: An aware datetime, or a naive one that is interpreted as UTC; ``None`` is allowed.

    Returns:
        Microseconds, or ``None`` when ``moment`` is ``None``.
    """
    if moment is None:
        return None
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return (aware - _EPOCH) // timedelta(microseconds=1)
