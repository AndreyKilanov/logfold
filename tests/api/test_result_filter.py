from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import logfold
from logfold.errors import ConfigError, NoLevelsError
from logfold.levels import LEVEL_NAMES, at_least, normalize_level, severity, summarize_levels


@pytest.fixture(scope="module")
def analysis(corpus_dir: Path) -> logfold.AnalysisResult:
    return logfold.analyze(str(corpus_dir / "app.log"), format="app")


@pytest.fixture(scope="module")
def comparison(corpus_dir: Path) -> logfold.DiffResult:
    return logfold.diff(str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app")


def test_levels_sums_the_records_per_level_least_severe_first(analysis: logfold.AnalysisResult) -> None:
    levels = analysis.levels
    assert list(levels) == sorted(levels, key=LEVEL_NAMES.index)
    assert set(levels) == {"DEBUG", "INFO", "WARN", "ERROR"}
    assert sum(levels.values()) == analysis.run.records


def test_a_format_without_levels_has_no_level_counts(corpus_dir: Path) -> None:
    assert logfold.analyze(str(corpus_dir / "nginx.log"), format="nginx").levels == {}


def test_filter_keeps_the_templates_at_or_above_a_level(analysis: logfold.AnalysisResult) -> None:
    kept = analysis.filter(min_level="WARN")
    assert 0 < len(kept.templates) < len(analysis.templates)
    assert {template.level for template in kept.templates} <= {"WARN", "ERROR", "FATAL"}
    assert kept.templates == tuple(t for t in analysis.templates if t.level in ("WARN", "ERROR", "FATAL"))


def test_filter_leaves_everything_else_as_it_was(analysis: logfold.AnalysisResult) -> None:
    kept = analysis.filter(min_level="ERROR")
    assert (kept.run, kept.metrics, kept.meta, kept.warnings) == (
        analysis.run,
        analysis.metrics,
        analysis.meta,
        analysis.warnings,
    )
    assert len(analysis.templates) > len(kept.templates)
    assert analysis.filter() == analysis


def test_filter_takes_any_case_and_the_warning_alias(analysis: logfold.AnalysisResult) -> None:
    assert analysis.filter(min_level="warn") == analysis.filter(min_level="WARN")
    assert analysis.filter(min_level="Warning") == analysis.filter(min_level="WARN")


def test_a_higher_level_never_keeps_more(analysis: logfold.AnalysisResult) -> None:
    counts = [len(analysis.filter(min_level=level).templates) for level in LEVEL_NAMES]
    assert counts == sorted(counts, reverse=True)
    assert counts[-1] == 0


def test_filter_by_count_and_by_level_combine(analysis: logfold.AnalysisResult) -> None:
    both = analysis.filter(min_level="INFO", min_count=100)
    assert both.templates
    assert all(t.count >= 100 and at_least(t.level, "INFO") for t in both.templates)
    assert both == analysis.filter(min_level="INFO").filter(min_count=100)
    assert all(t.count >= 100 for t in analysis.filter(min_count=100).templates)


def test_filter_rejects_an_unknown_level_with_a_hint(analysis: logfold.AnalysisResult) -> None:
    with pytest.raises(ConfigError, match="unknown level 'erro'") as caught:
        analysis.filter(min_level="erro")
    assert caught.value.hint == "did you mean 'ERROR'?"


def test_filter_refuses_a_result_whose_format_has_no_levels(corpus_dir: Path) -> None:
    nginx = logfold.analyze(str(corpus_dir / "nginx.log"), format="nginx")
    with pytest.raises(NoLevelsError, match="the nginx format gives no levels") as caught:
        nginx.filter(min_level="WARN")
    assert isinstance(caught.value, ConfigError)
    assert caught.value.format == "nginx"
    assert caught.value.hint is not None
    assert nginx.filter(min_count=1) == nginx


def test_an_empty_result_filters_to_an_empty_result(analysis: logfold.AnalysisResult) -> None:
    empty = dataclasses.replace(analysis, templates=())
    assert empty.filter(min_level="WARN").templates == ()


def test_a_template_with_an_unknown_level_name_is_dropped(analysis: logfold.AnalysisResult) -> None:
    odd = dataclasses.replace(analysis.templates[0], level="BANANA")
    patched = dataclasses.replace(analysis, templates=(odd, *analysis.templates[1:]))
    assert odd not in patched.filter(min_level="TRACE").templates


def test_diff_filter_keeps_the_entries_at_or_above_a_level(comparison: logfold.DiffResult) -> None:
    errors = comparison.filter(min_level="ERROR")
    for entries in (errors.new_templates, errors.disappeared, errors.changed):
        assert {e.level for e in entries} <= {"ERROR", "FATAL"}
    assert errors.new_templates
    assert len(errors.changed) < len(comparison.changed)
    assert errors.unchanged == comparison.unchanged
    assert (errors.before, errors.after, errors.config, errors.meta) == (
        comparison.before,
        comparison.after,
        comparison.config,
        comparison.meta,
    )


def test_diff_gates_see_the_filtered_lists(comparison: logfold.DiffResult) -> None:
    assert comparison.new_templates
    assert not comparison.filter(min_level="FATAL").new_templates
    assert comparison.filter(min_level="WARN").new_alerts == comparison.new_alerts


def test_diff_filter_without_a_level_changes_nothing(comparison: logfold.DiffResult) -> None:
    assert comparison.filter() is comparison


def test_diff_filter_rejects_a_bad_level(comparison: logfold.DiffResult) -> None:
    with pytest.raises(ConfigError, match="unknown level 'loud'"):
        comparison.filter(min_level="loud")


def test_diff_filter_refuses_entries_that_have_no_levels(comparison: logfold.DiffResult) -> None:
    levelless = dataclasses.replace(comparison.new_templates[0], level=None)
    result = dataclasses.replace(comparison, new_templates=(levelless,), disappeared=(), changed=())
    with pytest.raises(NoLevelsError):
        result.filter(min_level="WARN")
    nothing = dataclasses.replace(comparison, new_templates=(), disappeared=(), changed=())
    assert nothing.filter(min_level="WARN") == nothing


def test_level_helpers() -> None:
    assert normalize_level("error") == "ERROR"
    assert normalize_level("Warning") == "WARN"
    assert [severity(name) for name in LEVEL_NAMES] == list(range(len(LEVEL_NAMES)))
    assert severity(None) == -1
    assert severity("BANANA") == -1
    assert at_least("ERROR", "WARN") is True
    assert at_least("WARN", "WARN") is True
    assert at_least("INFO", "WARN") is False
    assert at_least(None, "TRACE") is False
    assert summarize_levels([0, 0, 3, 0, 1, 0]) == ("ERROR", {"INFO": 3, "ERROR": 1})
    assert summarize_levels([0] * 6) == (None, {})
