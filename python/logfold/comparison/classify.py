"""Classification of templates of two runs into new, disappeared, changed and unchanged."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from logfold.comparison.significance import apply_significance
from logfold.config import DiffConfig
from logfold.ext.matchers import DiffMatcher
from logfold.levels import summarize_levels
from logfold.model import DiffEntry, RunSummary, micros_to_datetime

if TYPE_CHECKING:
    from collections.abc import Sequence

    from logfold.engines.base import RunStatsData, TemplateStats


@dataclass(frozen=True, slots=True)
class Classification:
    """Output of :func:`classify`.

    Attributes:
        new: Entries present only in the second run.
        disappeared: Entries present only in the first run.
        changed: Entries present in both runs whose share changed significantly.
        unchanged: Number of entries present in both runs without a significant change.
    """

    new: tuple[DiffEntry, ...]
    disappeared: tuple[DiffEntry, ...]
    changed: tuple[DiffEntry, ...]
    unchanged: int


def _shares(
    before_count: int, after_count: int, before_total: int, after_total: int
) -> tuple[float, float, float | None]:
    before_share = before_count / before_total if before_total else 0.0
    after_share = after_count / after_total if after_total else 0.0
    ratio = after_share / before_share if before_count and after_count and before_share > 0 else None
    return before_share, after_share, ratio


def _entry(
    template_after: TemplateStats | None,
    template_before: TemplateStats | None,
    before_total: int,
    after_total: int,
    after_aware: bool,
    before_aware: bool,
) -> DiffEntry:
    primary = template_after if template_after is not None else template_before
    assert primary is not None
    before: RunStatsData | None = template_before.runs[0] if template_before is not None else None
    after: RunStatsData | None = template_after.runs[1] if template_after is not None else None
    before_count = before.count if before else 0
    after_count = after.count if after else 0
    before_share, after_share, ratio = _shares(before_count, after_count, before_total, after_total)
    summed = [0] * len(primary.runs[0].levels)
    for stats in (before, after):
        if stats is not None:
            summed = [x + y for x, y in zip(summed, stats.levels, strict=True)]
    level, levels = summarize_levels(summed)
    source = after if after is not None else before
    assert source is not None
    aware = after_aware if after is not None else before_aware
    return DiffEntry(
        id=primary.id,
        text=primary.text,
        before_count=before_count,
        after_count=after_count,
        before_share=before_share,
        after_share=after_share,
        ratio=ratio,
        level=level,
        levels=levels,
        example=source.example,
        first_seen=micros_to_datetime(source.first, aware),
        last_seen=micros_to_datetime(source.last, aware),
    )


def _factor(ratio: float | None) -> float:
    ratio = ratio or 1.0
    return max(ratio, 1.0 / ratio)


def _change_factor(entry: DiffEntry) -> float:
    return _factor(entry.ratio)


def classify(
    templates: Sequence[TemplateStats],
    before: RunSummary,
    after: RunSummary,
    config: DiffConfig,
    matcher: DiffMatcher,
) -> Classification:
    """Split templates into new, disappeared, changed and unchanged.

    A template is *new* when it occurs only in the second run, *disappeared* when only in the first, and *changed*
    when it occurs in both, its share of records moved by a factor of at least ``threshold_ratio`` (up or down) while
    either count is at least ``min_count``, and the move is significant (``significance``, see
    :func:`~logfold.comparison.significance.apply_significance`). The ``matcher`` pairs one-sided templates that
    describe the same event so they are compared as one template instead of being reported twice.

    Args:
        templates: Templates with statistics for exactly two runs.
        before: Counters of the first run.
        after: Counters of the second run.
        config: Comparison parameters.
        matcher: Pairs one-sided templates.

    Returns:
        The classification: ``new`` and ``disappeared`` most frequent first, ``changed`` with the largest score first.
    """
    both: list[tuple[TemplateStats | None, TemplateStats | None]] = []
    before_only: list[TemplateStats] = []
    after_only: list[TemplateStats] = []
    for template in templates:
        in_before = template.runs[0].count > 0
        in_after = template.runs[1].count > 0
        if in_before and in_after:
            both.append((template, template))
        elif in_before:
            before_only.append(template)
        elif in_after:
            after_only.append(template)

    paired_before: set[int] = set()
    paired_after: set[int] = set()
    for i, j in matcher.match([t.text for t in before_only], [t.text for t in after_only]):
        both.append((after_only[j], before_only[i]))
        paired_before.add(i)
        paired_after.add(j)

    def build(after_t: TemplateStats | None, before_t: TemplateStats | None) -> DiffEntry:
        return _entry(after_t, before_t, before.records, after.records, after.tz_aware, before.tz_aware)

    new = [build(t, None) for index, t in enumerate(after_only) if index not in paired_after]
    gone = [build(None, t) for index, t in enumerate(before_only) if index not in paired_before]
    changed: list[DiffEntry] = []
    unchanged = 0
    for after_t, before_t in both:
        before_count = before_t.runs[0].count if before_t is not None else 0
        after_count = after_t.runs[1].count if after_t is not None else 0
        _, _, ratio = _shares(before_count, after_count, before.records, after.records)
        if max(before_count, after_count) >= config.min_count and _factor(ratio) >= config.threshold_ratio:
            changed.append(build(after_t, before_t))
        else:
            unchanged += 1

    new = [e for e in new if e.after_count >= config.min_new_count]
    gone = [e for e in gone if e.before_count >= config.min_new_count]
    new.sort(key=lambda e: (-e.after_count, e.text))
    gone.sort(key=lambda e: (-e.before_count, e.text))
    changed.sort(key=lambda e: (-_change_factor(e), -max(e.before_count, e.after_count), e.text))
    return apply_significance(
        Classification(tuple(new), tuple(gone), tuple(changed), unchanged),
        before.records,
        after.records,
        config.significance,
    )
