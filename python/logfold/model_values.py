"""The values at the variable positions of a template.

Their distribution (``analyze(values=True)``) and which of them are new or gone between two runs
(``diff(new_values=True)``).
"""

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


@dataclass(frozen=True, slots=True)
class ValueChange:
    """How the values of one variable position differ between the two runs of a ``diff``.

    A value is new when the second run has it and the first does not, gone when it is the other way round. The lists
    hold the most frequent ones (at most 10, a value cut at 64 bytes); with ``examples="none"`` they are empty and the
    numbers remain, with ``examples="masked"`` the values have the masking rules applied and are summed.

    Attributes:
        position: Index of the token in the template.
        name: ``*`` or the name of the masking rule.
        new: The most frequent new values with the records that gave them, most frequent first and then by text.
        gone: The most frequent gone values with their records in the first run.
        new_distinct: How many different values are new.
        gone_distinct: How many different values are gone.
        shared_distinct: How many different values both runs have.
        before_distinct: How many different values the first run has.
        after_distinct: How many different values the second run has.
        capped: ``True`` when the position had more different values than the memory limit allows (1,000,000 for one
            position, 4,000,000 for a run). The lists are then empty and the numbers are lower bounds, because a value
            that looks new may only be one that was not counted.
    """

    position: int
    name: str
    new: tuple[tuple[str, int], ...]
    gone: tuple[tuple[str, int], ...]
    new_distinct: int
    gone_distinct: int
    shared_distinct: int
    before_distinct: int
    after_distinct: int
    capped: bool


@dataclass(frozen=True, slots=True)
class TemplateValueChanges:
    """The positions of a template, present in both runs, whose values differ.

    Attributes:
        id: Identifier of the template (see :class:`logfold.Template`).
        text: Text of the template.
        level: The most severe level of the template in either run, or ``None``.
        changes: The positions that differ, in order.
    """

    id: str
    text: str
    level: str | None
    changes: tuple[ValueChange, ...]
