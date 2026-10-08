"""Pooling of several baseline runs into the one "before" side of a comparison.

The engine mines every baseline and the second run in one pass with one template tree, as separate runs. Pooling turns
that result into the shape a comparison of two runs expects: counts, levels and records are summed over the baselines,
the first and last times are the earliest and the latest, and the templates that occur in too few baselines are taken
out as unstable.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from logfold.engines.base import MiningResult, RunColumns, RunCounters, TemplateTable
from logfold.errors import ConfigError
from logfold.levels import LEVEL_NAMES

MANY_BASELINES = 10


@dataclass(frozen=True, slots=True)
class PooledBaseline:
    """Baselines pooled against the second run.

    Attributes:
        table: Templates with two runs: the pooled baselines and the second run.
        before: Counters of the pooled baselines.
        after: Counters of the second run.
        unstable: Templates that occur in the second run and in some, but too few, baselines; they are left out of the
            table because they are neither new nor comparable.
    """

    table: TemplateTable
    before: RunCounters
    after: RunCounters
    unstable: int


def required_baselines(count: int, minimum: int | None) -> int:
    """Resolve the number of baselines a template must occur in to be compared.

    Args:
        count: Number of baselines.
        minimum: The configured minimum, or ``None`` for all baselines.

    Returns:
        The minimum, between 1 and ``count``.

    Raises:
        ConfigError: If the minimum is larger than the number of baselines.
    """
    if minimum is None:
        return count
    if minimum > count:
        raise ConfigError(f"min_baselines is {minimum}, but there are only {count} baselines")
    return minimum


def pool_info(infos: Sequence[RunCounters]) -> RunCounters:
    """Add up the counters of runs.

    Args:
        infos: Counters of the runs.

    Returns:
        The counters of the runs read as one.
    """
    return RunCounters(
        files=sum(i.files for i in infos),
        lines=sum(i.lines for i in infos),
        records=sum(i.records for i in infos),
        unparsed=sum(i.unparsed for i in infos),
        bytes=sum(i.bytes for i in infos),
        tz_aware=any(i.tz_aware for i in infos),
        overflowed=any(i.overflowed for i in infos),
        out_of_range=sum(i.out_of_range for i in infos),
        untimed=sum(i.untimed for i in infos),
    )


def _pool(runs: Sequence[RunColumns], rows: Sequence[int]) -> RunColumns:
    counts: list[int] = []
    first: list[int | None] = []
    last: list[int | None] = []
    levels: list[dict[str, int]] = []
    level: list[str | None] = []
    examples: list[str | None] = []
    for i in rows:
        counts.append(sum(run.counts[i] for run in runs))
        present = [run for run in runs if run.counts[i] > 0]
        starts = [t for run in present if (t := run.first[i]) is not None]
        ends = [t for run in present if (t := run.last[i]) is not None]
        first.append(min(starts) if starts else None)
        last.append(max(ends) if ends else None)
        merged = {name: total for name in LEVEL_NAMES if (total := sum(run.levels[i].get(name, 0) for run in runs))}
        levels.append(merged)
        level.append(next((name for name in reversed(LEVEL_NAMES) if name in merged), None))
        examples.append(next((run.examples[i] for run in present if run.examples[i] is not None), None))
    return RunColumns(counts, first, last, levels, level, examples)


def pool_baselines(mined: MiningResult, baselines: int, minimum: int) -> PooledBaseline:
    """Pool the first ``baselines`` runs of a result and keep the last run as the second run.

    Args:
        mined: A result with ``baselines + 1`` runs: the baselines, then the run to compare.
        baselines: Number of baselines.
        minimum: Number of baselines a template must occur in to stay (see :func:`required_baselines`).

    Returns:
        The pooled sides. A template stays when it occurs in at least ``minimum`` baselines, or in no baseline (then it
        is new when the second run has it). One that occurs in some but fewer baselines is unstable: it is left out,
        and counted when the second run has it too, so that it is reported neither as new, nor disappeared or changed.
    """
    table = mined.templates
    if baselines == 1:
        return PooledBaseline(table, mined.runs[0], mined.runs[1], 0)
    before = table.runs[:baselines]
    after = table.runs[baselines]
    keep: list[int] = []
    unstable = 0
    for i in range(len(table)):
        seen = sum(1 for run in before if run.counts[i] > 0)
        if seen >= minimum:
            keep.append(i)
        elif seen == 0:
            if after.counts[i] > 0:
                keep.append(i)
        elif after.counts[i] > 0:
            unstable += 1
    pooled = TemplateTable(
        ids=[table.ids[i] for i in keep],
        texts=[table.texts[i] for i in keep],
        runs=(_pool(before, keep), _pool([after], keep)),
    )
    return PooledBaseline(pooled, pool_info(mined.runs[:baselines]), mined.runs[baselines], unstable)


def baseline_warnings(names: Sequence[Sequence[str]], infos: Sequence[RunCounters]) -> list[str]:
    """Warn about baselines that do not help: empty ones, and more of them than are useful.

    Args:
        names: The inputs of every baseline.
        infos: Counters of every baseline, in the same order.

    Returns:
        One sentence per empty baseline when there are several baselines, and one when there are more than
        :data:`MANY_BASELINES`; otherwise nothing.
    """
    if len(infos) < 2:
        return []
    found = [
        f"baseline {','.join(files)} has no records, so no template can occur in all baselines"
        for files, info in zip(names, infos, strict=True)
        if info.records == 0
    ]
    if len(infos) > MANY_BASELINES:
        found.append(
            f"{len(infos)} baselines were read in full, which costs time and memory in proportion; "
            f"{MANY_BASELINES} or fewer recent good runs are enough to tell stable templates from noise"
        )
    return found
