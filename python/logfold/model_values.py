"""The distribution of the values at a variable position of a template (``analyze(values=True)``)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class NumericSummary:
    """The numbers among the values of a position, written as ``-?digits(.digits)?``.

    The percentiles come from logarithmic buckets and are within about 2.4% of the number that has that rank; the rank
    of a percentile ``q`` is ``floor(q * (count - 1))`` in the sorted numbers.

    Attributes:
        count: How many of the values were numbers.
        min: The smallest number.
        max: The largest number.
        mean: The mean of the numbers.
        p50: The median.
        p90: The 90th percentile.
        p99: The 99th percentile.
    """

    count: int
    min: float
    max: float
    mean: float
    p50: float
    p90: float
    p99: float


@dataclass(frozen=True, slots=True)
class ValueStats:
    """The values that the records of a template gave to one variable position.

    A position is a ``<*>`` (named ``*``) or a value that a default masking rule replaced (named by the rule, for
    example ``num``); the values that a mask set of the user hides are never counted. A token that holds several
    values of one rule gives them all to one position.

    Attributes:
        position: Index of the token in the template.
        name: ``*`` or the name of the masking rule.
        count: How many values the position got.
        top: The most frequent values with their counts, most frequent first and the values with the same count in order
            of their text (at most 10; a value is cut at 64 bytes). Empty with ``examples="none"``; with
            ``examples="masked"`` the values have the masking rules applied.
        distinct: How many different values are counted one by one: all of them unless ``capped``, then a lower bound.
        capped: ``True`` when more than 1000 different values were met, so that later new values are only in ``other``.
        other: How many values were not counted one by one.
        numeric: The numbers among the values, or ``None`` when there were none.
    """

    position: int
    name: str
    count: int
    top: tuple[tuple[str, int], ...]
    distinct: int
    capped: bool
    other: int
    numeric: NumericSummary | None
