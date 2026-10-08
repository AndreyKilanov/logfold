"""Classification of two runs in the native extension, and the building of the reported entries.

The extension joins the templates of the two runs, pairs the ones that exist in one run only with a built-in matcher and
decides which are new, disappeared, changed or unchanged, working on columns of texts and counts. Only the reported
templates become :class:`~logfold.model.DiffEntry` objects here. The pure-Python :func:`logfold.comparison.classify`
is the reference: it gives the same entries (see the differential tests) and handles everything the extension does not
(plugin matchers, the pure-Python engine, values the extension cannot take).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from logfold import _bridge
from logfold.comparison import Classification, apply_significance
from logfold.config import DiffConfig
from logfold.engines.base import TemplateTable
from logfold.levels import LEVEL_NAMES
from logfold.model import (
    AnalysisResult,
    DiffEntry,
    RunSummary,
    datetime_to_micros,
    micros_to_datetime,
)

Row = tuple[str, str, int, "datetime | None", "datetime | None", Mapping[str, int], "str | None"]
Spec = tuple[str, "float | None", "Sequence[tuple[str, str]] | None"]


@dataclass(frozen=True, slots=True)
class Side:
    """The templates of one run: columns for the extension and a row accessor for the entries.

    Attributes:
        texts: Template texts.
        counts: Records per template.
        total: Records of the run.
        row: Returns ``(id, text, count, first_seen, last_seen, levels, example)`` of the template at an index.
    """

    texts: list[str]
    counts: list[int]
    total: int
    row: Callable[[int], Row]


def table_side(table: TemplateTable, run: int, summary: RunSummary) -> Side:
    """Describe one run of an engine result; templates without records in the run are left out.

    Args:
        table: The templates of the result.
        run: Index of the run.
        summary: Counters of the run.

    Returns:
        The side; its indices are positions among the templates that occur in the run.
    """
    columns = table.runs[run]
    present = [i for i, count in enumerate(columns.counts) if count > 0]
    aware = summary.tz_aware

    def row(position: int) -> Row:
        i = present[position]
        return (
            table.ids[i],
            table.texts[i],
            columns.counts[i],
            micros_to_datetime(columns.first[i], aware),
            micros_to_datetime(columns.last[i], aware),
            columns.levels[i],
            columns.examples[i],
        )

    return Side([table.texts[i] for i in present], [columns.counts[i] for i in present], summary.records, row)


def _moment(value: datetime | None, aware: bool) -> datetime | None:
    if value is None or (value.tzinfo is not None) == aware:
        return value
    return micros_to_datetime(datetime_to_micros(value), aware)


def result_side(result: AnalysisResult) -> Side:
    """Describe a saved or freshly analyzed result.

    Args:
        result: The analysis result.

    Returns:
        The side; its indices are positions in ``result.templates``.
    """
    templates = result.templates
    aware = result.run.tz_aware

    def row(i: int) -> Row:
        t = templates[i]
        return (t.id, t.text, t.count, _moment(t.first_seen, aware), _moment(t.last_seen, aware), t.levels, t.example)

    return Side([t.text for t in templates], [t.count for t in templates], result.run.records, row)


def _levels(*parts: Mapping[str, int]) -> tuple[str | None, dict[str, int]]:
    merged: dict[str, int] = {}
    level: str | None = None
    for name in LEVEL_NAMES:
        value = sum(part.get(name, 0) for part in parts)
        if value > 0:
            merged[name] = value
            level = name
    return level, merged


def _share(count: int, total: int) -> float:
    return count / total if total else 0.0


def _entry(
    identifier: str,
    text: str,
    counts: tuple[int, int],
    shares: tuple[float, float],
    ratio: float | None,
    severity: tuple[str | None, dict[str, int]],
    source: tuple[str | None, datetime | None, datetime | None],
) -> DiffEntry:
    return DiffEntry(
        identifier, text, counts[0], counts[1], shares[0], shares[1], ratio, severity[0], severity[1], *source
    )


def classify_native(
    before: Side,
    after: Side,
    config: DiffConfig,
    spec: Spec,
    example: Callable[[str | None], str | None],
) -> Classification | None:
    """Classify two runs in the extension.

    Args:
        before: The first run.
        after: The second run.
        config: Comparison parameters.
        spec: The built-in matcher as ``(name, threshold, rules)``.
        example: Converts the example of a reported template (keeps, masks or drops it).

    Returns:
        The classification, or ``None`` when the extension cannot take the data (a text it cannot pass, a count it
        cannot hold, a template listed twice in one run) and the reference should run.
    """
    kind, threshold, rules = spec
    if len(set(before.texts)) != len(before.texts) or len(set(after.texts)) != len(after.texts):
        return None
    try:
        new, gone, changed, unchanged = _bridge.compare_runs(
            (before.texts, before.counts, before.total),
            (after.texts, after.counts, after.total),
            (config.threshold_ratio, config.min_count, config.min_new_count),
            kind,
            threshold,
            rules,
        )
    except (UnicodeError, ValueError, OverflowError):
        return None
    new_entries = []
    for j in new:
        identifier, text, count, first, last, levels, sample = after.row(j)
        level, merged = _levels(levels)
        new_entries.append(
            _entry(
                identifier,
                text,
                (0, count),
                (0.0, _share(count, after.total)),
                None,
                (level, merged),
                (example(sample), first, last),
            )
        )
    gone_entries = []
    for i in gone:
        identifier, text, count, first, last, levels, sample = before.row(i)
        level, merged = _levels(levels)
        gone_entries.append(
            _entry(
                identifier,
                text,
                (count, 0),
                (_share(count, before.total), 0.0),
                None,
                (level, merged),
                (example(sample), first, last),
            )
        )
    changed_entries = []
    for i, j, before_share, after_share, ratio in changed:
        _, _, before_count, _, _, before_levels, _ = before.row(i)
        identifier, text, after_count, first, last, after_levels, sample = after.row(j)
        changed_entries.append(
            _entry(
                identifier,
                text,
                (before_count, after_count),
                (before_share, after_share),
                ratio,
                _levels(before_levels, after_levels),
                (example(sample), first, last),
            )
        )
    return apply_significance(
        Classification(tuple(new_entries), tuple(gone_entries), tuple(changed_entries), unchanged),
        before.total,
        after.total,
        config.significance,
    )
