"""Statistical significance of a change of a template's share between two runs.

A template with ``a`` records out of ``A`` before and ``b`` out of ``B`` after forms a 2x2 table (the template against
all other records, before against after). The G statistic of that table follows a chi-square distribution with one
degree of freedom when the share did not change, so ``p = erfc(sqrt(G / 2))``. Only ``math`` is used; the computation
runs in Python for every engine, so all of them report the same numbers.
"""

from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from logfold.comparison.classify import Classification

__all__ = ["apply_significance", "g_test"]

_SCORE_DIGITS = 6
_P_DIGITS = 6


def g_test(before_count: int, after_count: int, before_total: int, after_total: int) -> tuple[float, float]:
    """Test whether a template's share of records differs between two runs.

    Args:
        before_count: Records of the template in the first run.
        after_count: Records of the template in the second run.
        before_total: Records of the first run.
        after_total: Records of the second run.

    Returns:
        ``(score, p_value)``: the G statistic and the probability of a difference at least this large by chance. The
        score is 0 and the p-value 1 when there are no records. A count above the total of its run (inconsistent
        input, for example a hand-edited saved result) is taken as equal to the total.
    """
    total = before_total + after_total
    if total <= 0 or before_total <= 0 or after_total <= 0:
        return 0.0, 1.0
    before_count = min(max(before_count, 0), before_total)
    after_count = min(max(after_count, 0), after_total)
    with_template = before_count + after_count
    cells = (
        (before_count, before_total, with_template),
        (before_total - before_count, before_total, total - with_template),
        (after_count, after_total, with_template),
        (after_total - after_count, after_total, total - with_template),
    )
    statistic = 0.0
    for observed, row, column in cells:
        if observed > 0:
            statistic += observed * math.log(observed * total / (row * column))
    score = max(2.0 * statistic, 0.0)
    return score, math.erfc(math.sqrt(score / 2.0))


def apply_significance(
    classification: Classification, before_total: int, after_total: int, significance: float
) -> Classification:
    """Score the changed templates, drop the ones that may be noise and sort the rest by score.

    ``new`` and ``disappeared`` are left alone. A changed template whose p-value is above ``significance`` is counted as
    unchanged.

    Args:
        classification: The classification by ratio and count.
        before_total: Records of the first run.
        after_total: Records of the second run.
        significance: Highest p-value that is still reported, in ``(0, 1]``; 1 keeps every changed template.

    Returns:
        The classification with ``score`` and ``p_value`` on every changed entry, largest score first.
    """
    kept = []
    dropped = 0
    for entry in classification.changed:
        score, p_value = g_test(entry.before_count, entry.after_count, before_total, after_total)
        if p_value > significance:
            dropped += 1
            continue
        kept.append(
            dataclasses.replace(entry, score=round(score, _SCORE_DIGITS), p_value=float(f"{p_value:.{_P_DIGITS}g}"))
        )
    kept.sort(key=lambda e: (-(e.score or 0.0), -max(e.before_count, e.after_count), e.text))
    return dataclasses.replace(classification, changed=tuple(kept), unchanged=classification.unchanged + dropped)
