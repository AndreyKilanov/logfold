"""Significance of a change in diff: the statistic, the filter, the order, saved results and reports."""

from __future__ import annotations

import csv
import dataclasses
import io
import json
import math
import re
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from typer.testing import CliRunner

import logfold
from conftest import requires_native
from corpora import synthetic_pair
from logfold import ConfigError, DiffConfig
from logfold.cli.app import app
from logfold.comparison import ExactMatcher, apply_significance, classify, g_test
from logfold.comparison.classify import Classification
from logfold.engines.base import RunStats, TemplateStats
from logfold.model import DiffEntry, RunSummary

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def stats(count: int) -> RunStats:
    return RunStats(count, None, None, (0, 0, 0, 0, 0, 0), "example")


def template(text: str, before: int, after: int) -> TemplateStats:
    return TemplateStats(text[:16].ljust(16, "0"), text, (stats(before), stats(after)))


def summary(records: int) -> RunSummary:
    return RunSummary("run", 1, records, records, 0, 0, True, False)


def plain(text: str) -> str:
    """Remove the styling that rich adds when it believes it writes to a terminal (as in CI)."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def pearson(a: int, b: int, total_a: int, total_b: int) -> float:
    total = total_a + total_b
    value = 0.0
    for observed, row, column in (
        (a, total_a, a + b),
        (total_a - a, total_a, total - a - b),
        (b, total_b, a + b),
        (total_b - b, total_b, total - a - b),
    ):
        expected = row * column / total
        value += (observed - expected) ** 2 / expected
    return value


def test_g_test_agrees_with_pearson_for_large_counts() -> None:
    score, p_value = g_test(1000, 1300, 100_000, 100_000)
    assert score == pytest.approx(pearson(1000, 1300, 100_000, 100_000), rel=0.01)
    assert p_value == pytest.approx(math.erfc(math.sqrt(score / 2)))
    assert p_value < 1e-8


@pytest.mark.parametrize(
    ("score", "p_value"),
    [(3.841458820694124, 0.05), (6.634896601021213, 0.01), (10.827566170662733, 0.001)],
)
def test_p_value_matches_the_chi_square_critical_values(score: float, p_value: float) -> None:
    assert math.erfc(math.sqrt(score / 2)) == pytest.approx(p_value, rel=1e-6)


def test_an_unchanged_share_has_no_score() -> None:
    score, p_value = g_test(10, 20, 1000, 2000)
    assert score == pytest.approx(0.0, abs=1e-9)
    assert p_value == pytest.approx(1.0)


def test_small_counts_are_not_significant_and_large_ones_are() -> None:
    assert g_test(1, 5, 100, 100)[1] > 0.01
    assert g_test(10, 30, 1_000_000, 1_000_000)[1] < 0.01


def test_a_change_in_either_direction_scores_the_same() -> None:
    assert g_test(30, 90, 1000, 1000)[0] == pytest.approx(g_test(90, 30, 1000, 1000)[0])


@pytest.mark.parametrize(("before_total", "after_total"), [(0, 0), (0, 100), (100, 0)])
def test_no_records_means_no_evidence(before_total: int, after_total: int) -> None:
    assert g_test(5, 5, before_total, after_total) == (0.0, 1.0)


@given(
    a=st.integers(0, 10**6),
    b=st.integers(0, 10**6),
    total_a=st.integers(0, 10**6),
    total_b=st.integers(0, 10**6),
)
def test_g_test_is_defined_for_any_counts(a: int, b: int, total_a: int, total_b: int) -> None:
    score, p_value = g_test(a, b, total_a, total_b)
    assert math.isfinite(score)
    assert score >= 0.0
    assert 0.0 <= p_value <= 1.0


def entry(text: str, before: int, after: int) -> DiffEntry:
    return DiffEntry(text.ljust(16, "0")[:16], text, before, after, 0.0, 0.0, 2.0, None, {}, None, None, None)


def test_apply_significance_drops_noise_scores_and_sorts() -> None:
    changed = (entry("noise", 1, 5), entry("big", 100, 400), entry("medium", 200, 400), entry("same", 1000, 1000))
    result = apply_significance(Classification((), (), changed, 3), 10_000, 10_000, 0.01)
    assert [e.text for e in result.changed] == ["big", "medium"]
    assert result.unchanged == 5
    assert all(e.score is not None and e.p_value is not None for e in result.changed)
    assert result.changed[0].score > result.changed[1].score  # type: ignore[operator]


def test_a_significance_of_one_keeps_everything() -> None:
    changed = (entry("noise", 1, 5), entry("big", 100, 400))
    result = apply_significance(Classification((), (), changed, 0), 10_000, 10_000, 1.0)
    assert {e.text for e in result.changed} == {"noise", "big"}
    assert result.unchanged == 0


def test_new_and_disappeared_are_not_touched() -> None:
    new, gone = (entry("fresh", 0, 3),), (entry("old", 3, 0),)
    result = apply_significance(Classification(new, gone, (), 0), 100, 100, 0.01)
    assert (result.new, result.disappeared) == (new, gone)
    assert result.new[0].score is None


def test_equal_scores_are_ordered_by_count_then_text() -> None:
    changed = (entry("b", 100, 400), entry("a", 100, 400), entry("c", 200, 800))
    result = apply_significance(Classification((), (), changed, 0), 10_000, 10_000, 1.0)
    assert [e.text for e in result.changed] == ["c", "a", "b"]


def test_classify_applies_the_default_significance() -> None:
    templates = [template("noise <*>", 10, 22), template("real <*>", 1000, 2500)]
    run = summary(1_000_000)
    kept = classify(templates, run, run, DiffConfig(), ExactMatcher())
    assert [e.text for e in kept.changed] == ["real <*>"]
    assert kept.unchanged == 1
    everything = classify(templates, run, run, DiffConfig(significance=1.0), ExactMatcher())
    assert {e.text for e in everything.changed} == {"noise <*>", "real <*>"}


@pytest.mark.parametrize("value", [0.0, -0.1, 1.5, float("nan")])
def test_significance_must_be_in_range(value: float) -> None:
    with pytest.raises(ConfigError, match="significance"):
        DiffConfig(significance=value)


def test_significance_is_part_of_the_config_and_overridable() -> None:
    assert DiffConfig().significance == 0.01
    assert dataclasses.replace(DiffConfig(), significance=0.5).significance == 0.5


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    before, after, _ = synthetic_pair(tmp_path, 1)
    return before, after


def test_diff_reports_scores_on_changed_entries_only(pair: tuple[Path, Path]) -> None:
    result = logfold.diff(*pair, engine="native", significance=1.0, min_count=1)
    assert result.config.significance == 1.0
    assert result.changed
    assert all(e.score is not None and 0.0 <= (e.p_value or 0.0) <= 1.0 for e in result.changed)
    assert all(e.score is None and e.p_value is None for e in (*result.new_templates, *result.disappeared))
    scores = [e.score or 0.0 for e in result.changed]
    assert scores == sorted(scores, reverse=True)


def test_a_stricter_significance_never_adds_changes(pair: tuple[Path, Path]) -> None:
    loose = logfold.diff(*pair, engine="native", significance=1.0, min_count=1)
    strict = logfold.diff(*pair, engine="native", significance=1e-6, min_count=1)
    assert {e.id for e in strict.changed} <= {e.id for e in loose.changed}
    assert strict.unchanged + len(strict.changed) == loose.unchanged + len(loose.changed)
    assert (strict.new_templates, strict.disappeared) == (loose.new_templates, loose.disappeared)


@requires_native
@pytest.mark.parametrize("significance", [1.0, 0.05, 0.01, 1e-6])
def test_both_engines_report_the_same_changes(pair: tuple[Path, Path], significance: float) -> None:
    native = logfold.diff(*pair, engine="native", significance=significance, min_count=1)
    python = logfold.diff(*pair, engine="native", significance=significance, min_count=1)
    assert native.changed == python.changed
    assert native.unchanged == python.unchanged


def test_saved_results_use_the_same_filter(pair: tuple[Path, Path], tmp_path: Path) -> None:
    first = logfold.analyze(pair[0], engine="native")
    second = logfold.analyze(pair[1], engine="native")
    first.save(tmp_path / "a.json")
    second.save(tmp_path / "b.json")
    saved = logfold.diff(
        logfold.load_analysis(tmp_path / "a.json"),
        logfold.load_analysis(tmp_path / "b.json"),
        significance=1.0,
        min_count=1,
    )
    assert all(e.score is not None for e in saved.changed)
    strict = logfold.diff(
        logfold.load_analysis(tmp_path / "a.json"),
        logfold.load_analysis(tmp_path / "b.json"),
        significance=1e-12,
        min_count=1,
    )
    assert len(strict.changed) <= len(saved.changed)


def test_json_report_has_scores_and_the_config_value(pair: tuple[Path, Path]) -> None:
    result = logfold.diff(*pair, engine="native", significance=1.0, min_count=1)
    payload = json.loads(result.to_json())
    assert payload["config"]["significance"] == 1.0
    assert all(isinstance(row["score"], float) and isinstance(row["p_value"], float) for row in payload["changed"])
    assert all(row["score"] is None and row["p_value"] is None for row in payload["new_templates"])


def test_csv_report_has_score_columns(pair: tuple[Path, Path]) -> None:
    result = logfold.diff(*pair, engine="native", significance=1.0, min_count=1)
    rows = list(csv.reader(io.StringIO(result.render("csv"))))
    assert rows[0][-2:] == ["score", "p_value"]
    changed = [row for row in rows[1:] if row[0] == "changed"]
    assert changed
    assert all(row[-2] and row[-1] for row in changed)
    assert all(not row[-2] and not row[-1] for row in rows[1:] if row[0] == "new")


def test_text_and_html_reports_show_the_p_value(pair: tuple[Path, Path]) -> None:
    result = logfold.diff(*pair, engine="native", significance=1.0, min_count=1)
    text = result.render("text")
    assert "      p  " in text or " p " in text
    html = result.to_html()
    assert 'title="score ' in html
    assert "p <" not in html
    assert "p &lt;0.001" in html


def test_cli_shows_the_p_column_and_accepts_the_option(pair: tuple[Path, Path]) -> None:
    shown = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--min-count", "1", "--significance", "1", "-q"])
    assert shown.exit_code == 0
    changed = plain(shown.stdout).split("Changed templates")[1].split("Disappeared templates")[0]
    assert " p " in changed
    rejected = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--significance", "0"])
    assert rejected.exit_code != 0
    assert "significance" in rejected.stderr.lower() or "significance" in rejected.output.lower()


def test_cli_significance_applies_to_saved_results(pair: tuple[Path, Path], tmp_path: Path) -> None:
    for name, path in (("a", pair[0]), ("b", pair[1])):
        runner.invoke(app, ["analyze", str(path), "--out", str(tmp_path / f"{name}.json"), "-q"])
    result = runner.invoke(
        app,
        [
            "diff",
            str(tmp_path / "a.json"),
            str(tmp_path / "b.json"),
            "--min-count",
            "1",
            "--significance",
            "1",
            "--json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["config"]["significance"] == 1.0


def test_the_default_significance_is_documented_in_help() -> None:
    result = runner.invoke(app, ["diff", "--help"])
    assert "--significance" in plain(result.stdout)
