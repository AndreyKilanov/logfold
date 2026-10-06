"""The native comparison gives exactly the classification of the pure-Python reference.

Both are run on random runs: templates present in one run or both, counts of zero, totals of zero, every built-in
matcher and random thresholds. The entries must be equal, field by field, including the floats.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from logfold import DiffConfig
from logfold.api.comparing import classify_native, result_side, table_side
from logfold.api.matching import native_spec
from logfold.api.saved import _join_saved
from logfold.comparison import ExactMatcher, TokenSubsetMatcher, classify
from logfold.engines.base import RunStatsData, TemplateStats, TemplateTable
from logfold.levels import summarize_levels
from logfold.model import AnalysisResult, ResultMeta, RunMetrics, RunSummary, Template
from logfold.plugins.matchers import JaccardIdfMatcher, JaccardMatcher, OverlapMatcher, RulesMatcher

pytestmark = requires_native

WORDS = ["a", "b", "c", "d", "<*>", "<*>", "user", "failed", "<NUM>"]
EPOCH_US = 1_700_000_000_000_000


def matchers() -> list[object]:
    jaccard = JaccardMatcher()
    jaccard.threshold = 0.5
    idf = JaccardIdfMatcher()
    idf.threshold = 0.3
    overlap = OverlapMatcher()
    overlap.threshold = 0.6
    rules = RulesMatcher([("a b", "c d"), ("user <*>", "failed <NUM>"), ("a", "b")])
    return [
        ExactMatcher(),
        TokenSubsetMatcher(),
        JaccardMatcher(),
        jaccard,
        JaccardIdfMatcher(),
        idf,
        OverlapMatcher(),
        overlap,
        rules,
    ]


def summary(records: int, aware: bool) -> RunSummary:
    return RunSummary("run", 1, records, records, 0, 0, aware, False)


def random_stats(rng: random.Random, count: int) -> RunStatsData:
    if count == 0:
        return RunStatsData(0, None, None, (0,) * 6, None)
    levels = [0] * 6
    for _ in range(min(count, 5)):
        levels[rng.randrange(6)] += 1
    first = EPOCH_US + rng.randrange(10**9) if rng.random() < 0.8 else None
    last = first + rng.randrange(10**6) if first is not None else None
    return RunStatsData(
        count, first, last, tuple(levels), f"example {rng.randrange(100)}" if rng.random() < 0.9 else None
    )


def random_templates(rng: random.Random, size: int) -> list[TemplateStats]:
    texts: dict[str, None] = {}
    while len(texts) < size:
        texts[" ".join(rng.choice(WORDS) for _ in range(rng.randrange(0, 5)))] = None
    templates = []
    for text in texts:
        counts = [rng.choice([0, 0, 1, 2, 5, 10, 50, 400]) for _ in range(2)]
        templates.append(
            TemplateStats(f"{abs(hash(text)) % 16**16:016x}", text, tuple(random_stats(rng, c) for c in counts))
        )
    return templates


def reference(
    templates: list[TemplateStats], before: RunSummary, after: RunSummary, config: DiffConfig, matcher: object
):
    return classify(templates, before, after, config, matcher)  # type: ignore[arg-type]


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    seed=st.integers(0, 10**6),
    size=st.integers(0, 40),
    ratio=st.sampled_from([1.0, 1.5, 2.0, 3.7, 10.0]),
    min_count=st.sampled_from([0, 1, 5, 10, 100]),
    min_new=st.sampled_from([0, 1, 3, 50]),
    totals=st.sampled_from([(None, None), (0, 0), (1000, 0), (0, 1000), (50, 50), (10**6, 7)]),
    aware=st.booleans(),
)
def test_native_classification_equals_the_reference_for_engine_results(
    seed: int, size: int, ratio: float, min_count: int, min_new: int, totals: tuple[int | None, int | None], aware: bool
) -> None:
    rng = random.Random(seed)
    templates = random_templates(rng, size)
    sums = [sum(t.runs[r].count for t in templates) for r in range(2)]
    before_total = sums[0] if totals[0] is None else totals[0]
    after_total = sums[1] if totals[1] is None else totals[1]
    before, after = summary(before_total, aware), summary(after_total, not aware if rng.random() < 0.3 else aware)
    table = TemplateTable.from_stats(templates, 2)
    for matcher in matchers():
        config = DiffConfig(threshold_ratio=ratio, min_count=min_count, min_new_count=min_new, matcher=matcher.name)  # type: ignore[attr-defined]
        spec = native_spec(matcher)  # type: ignore[arg-type]
        assert spec is not None
        expected = reference(templates, before, after, config, matcher)
        got = classify_native(
            table_side(table, 0, before), table_side(table, 1, after), config, spec, lambda text: text
        )
        assert got == expected, (matcher.name, config)  # type: ignore[attr-defined]


def moment(value: int | None, aware: bool) -> datetime | None:
    if value is None:
        return None
    instant = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=value)
    return instant if aware else instant.replace(tzinfo=None)


def to_result(templates: list[TemplateStats], run: int, records: int, aware: bool) -> AnalysisResult:
    rows = []
    for item in templates:
        stats = item.runs[run]
        if stats.count == 0:
            continue
        level, levels = summarize_levels(stats.levels)
        first, last = moment(stats.first, aware), moment(stats.last, aware)
        rows.append(Template(item.id, item.text, stats.count, first, last, stats.example, level, levels))
    metrics = RunMetrics("native", "sequential", 1, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
    meta = ResultMeta(1, 1, "test", "0" * 12, "app", False)
    return AnalysisResult(tuple(rows), summary(records, aware), metrics, meta)


def test_the_random_runs_are_not_vacuous() -> None:
    kinds = {"new": 0, "disappeared": 0, "changed": 0, "unchanged": 0, "paired": 0}
    for seed in range(60):
        rng = random.Random(seed)
        templates = random_templates(rng, 30)
        table = TemplateTable.from_stats(templates, 2)
        sums = [sum(t.runs[r].count for t in templates) for r in range(2)]
        before, after = summary(sums[0], True), summary(sums[1], True)
        config = DiffConfig(threshold_ratio=1.5, min_count=1, min_new_count=1, matcher="token_subset")
        got = classify_native(
            table_side(table, 0, before),
            table_side(table, 1, after),
            config,
            ("token_subset", None, None),
            lambda text: text,
        )
        assert got is not None
        known = {t.text for t in templates if t.runs[0].count > 0}
        kinds["new"] += len(got.new)
        kinds["disappeared"] += len(got.disappeared)
        kinds["changed"] += len(got.changed)
        kinds["unchanged"] += got.unchanged
        kinds["paired"] += sum(1 for entry in got.changed if entry.text not in known)
    assert all(value > 0 for value in kinds.values()), kinds


@settings(max_examples=250, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(
    seed=st.integers(0, 10**6),
    size=st.integers(0, 40),
    ratio=st.sampled_from([1.0, 2.0, 3.7]),
    min_count=st.sampled_from([0, 5, 10]),
    min_new=st.sampled_from([0, 1, 3]),
    aware=st.booleans(),
)
def test_native_classification_equals_the_reference_for_saved_results(
    seed: int, size: int, ratio: float, min_count: int, min_new: int, aware: bool
) -> None:
    rng = random.Random(seed)
    templates = random_templates(rng, size)
    sums = [sum(t.runs[r].count for t in templates) for r in range(2)]
    first, second = to_result(templates, 0, sums[0], aware), to_result(templates, 1, sums[1], aware)
    for matcher in matchers():
        config = DiffConfig(threshold_ratio=ratio, min_count=min_count, min_new_count=min_new, matcher=matcher.name)  # type: ignore[attr-defined]
        spec = native_spec(matcher)  # type: ignore[arg-type]
        assert spec is not None
        expected = classify(_join_saved(first, second), first.run, second.run, config, matcher)  # type: ignore[arg-type]
        got = classify_native(result_side(first), result_side(second), config, spec, lambda text: text)
        assert got == expected, (matcher.name, config)  # type: ignore[attr-defined]


def test_unusable_values_fall_back_to_the_reference(tmp_path) -> None:  # type: ignore[no-untyped-def]
    rng = random.Random(3)
    templates = random_templates(rng, 12)
    first, second = to_result(templates, 0, 1000, True), to_result(templates, 1, 1000, True)
    broken = Template("0" * 16, "user \ud800 failed", 7, None, None, None, None, {})
    odd = AnalysisResult((*second.templates, broken), second.run, second.metrics, second.meta)
    result = logfold.diff(first, odd, matcher="token_subset", min_count=0)
    assert result.config.matcher == "token_subset"
    negative = Template("1" * 16, "negative count", -3, None, None, None, None, {})
    odd = AnalysisResult((*second.templates, negative), second.run, second.metrics, second.meta)
    assert logfold.diff(first, odd, min_count=0).unchanged >= 0


@pytest.mark.parametrize("matcher", ["exact", "token_subset", "jaccard"])
def test_public_diff_matches_the_pure_python_engine(tmp_path, matcher: str) -> None:  # type: ignore[no-untyped-def]
    from corpora import synthetic_pair

    before, after, _truth = synthetic_pair(tmp_path, 12)
    native_result = logfold.diff(str(before), str(after), format="app", matcher=matcher, engine="native")
    python_result = logfold.diff(str(before), str(after), format="app", matcher=matcher, engine="python")
    assert native_result.new_templates == python_result.new_templates
    assert native_result.disappeared == python_result.disappeared
    assert native_result.changed == python_result.changed
    assert native_result.unchanged == python_result.unchanged


def test_template_table_rows_reject_slices() -> None:
    table = TemplateTable.from_stats(random_templates(random.Random(1), 5), 2)
    assert table[-1] == list(table)[-1]
    with pytest.raises(TypeError, match="integers"):
        table[1:3]  # type: ignore[index]


def test_a_template_listed_twice_in_one_result_runs_the_reference() -> None:
    rng = random.Random(8)
    templates = random_templates(rng, 10)
    first, second = to_result(templates, 0, 500, True), to_result(templates, 1, 500, True)
    twice = AnalysisResult((*first.templates, first.templates[0]), first.run, first.metrics, first.meta)
    config = DiffConfig(min_count=0)
    assert (
        classify_native(result_side(twice), result_side(second), config, ("exact", None, None), lambda text: text)
        is None
    )
    expected = classify(_join_saved(twice, second), twice.run, second.run, config, ExactMatcher())
    got = logfold.diff(twice, second, min_count=0)
    assert (got.new_templates, got.disappeared, got.changed, got.unchanged) == (
        expected.new,
        expected.disappeared,
        expected.changed,
        expected.unchanged,
    )
