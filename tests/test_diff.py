from __future__ import annotations

import random
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold import DiffConfig
from logfold.comparison import ExactMatcher, TokenSubsetMatcher, classify
from logfold.engines.base import RunStatsData, TemplateStats
from logfold.model import RunSummary


def stats(count: int, levels: tuple[int, ...] = (0, 0, 0, 0, 0, 0)) -> RunStatsData:
    return RunStatsData(count, None, None, levels, "example")


def template(text: str, before: int, after: int, levels: tuple[int, ...] = (0, 0, 0, 0, 0, 0)) -> TemplateStats:
    return TemplateStats(text[:16].ljust(16, "0"), text, (stats(before, levels), stats(after, levels)))


def summary(records: int) -> RunSummary:
    return RunSummary("run", 1, records, records, 0, 0, True, False)


def test_classify_categories_and_normalization() -> None:
    templates = [
        template("steady <*>", 100, 200),
        template("grew <*>", 10, 100),
        template("shrank <*>", 100, 10),
        template("brand new", 0, 7, (0, 0, 0, 0, 7, 0)),
        template("gone away", 5, 0),
        template("tiny change", 3, 9),
    ]
    result = classify(templates, summary(1000), summary(2000), DiffConfig(), ExactMatcher())
    assert [e.text for e in result.new] == ["brand new"]
    assert result.new[0].level == "ERROR"
    assert [e.text for e in result.disappeared] == ["gone away"]
    changed = {e.text: e.ratio for e in result.changed}
    assert set(changed) == {"grew <*>", "shrank <*>"}
    assert changed["grew <*>"] == pytest.approx((100 / 2000) / (10 / 1000))
    assert changed["shrank <*>"] == pytest.approx((10 / 2000) / (100 / 1000))
    assert result.unchanged == 2


def test_classify_thresholds_and_min_counts() -> None:
    templates = [template("a <*>", 10, 30), template("b <*>", 1, 5), template("c", 0, 1)]
    run = summary(100)

    def changed(config: DiffConfig) -> list[str]:
        return [e.text for e in classify(templates, run, run, config, ExactMatcher()).changed]

    assert changed(DiffConfig(threshold_ratio=4.0, min_count=2)) == ["b <*>"]
    assert changed(DiffConfig(threshold_ratio=2.0, min_count=2)) == ["b <*>", "a <*>"]
    assert changed(DiffConfig(threshold_ratio=2.0, min_count=6)) == ["a <*>"]
    assert changed(DiffConfig(threshold_ratio=10.0, min_count=0)) == []
    hidden = classify(templates, run, run, DiffConfig(min_new_count=2), ExactMatcher())
    assert hidden.new == ()


def test_token_subset_matcher_pairs_generalizations() -> None:
    before = ["user alice failed", "disk full on sda", "only before here"]
    after = ["user <*> failed", "disk full on <*>", "only after here"]
    pairs = TokenSubsetMatcher().match(before, after)
    assert sorted(pairs) == [(0, 0), (1, 1)]
    assert ExactMatcher().match(before, after) == []


def test_matcher_removes_false_new_and_disappeared() -> None:
    templates = [template("user alice failed", 40, 0), template("user <*> failed", 0, 45)]
    exact = classify(templates, summary(100), summary(100), DiffConfig(), ExactMatcher())
    assert len(exact.new) == 1
    assert len(exact.disappeared) == 1
    merged = classify(templates, summary(100), summary(100), DiffConfig(), TokenSubsetMatcher())
    assert merged.new == ()
    assert merged.disappeared == ()
    assert merged.unchanged == 1


def synthetic_pair(tmp_path: Path, seed: int) -> tuple[Path, Path, dict[str, set[str]]]:
    rng = random.Random(seed)
    base = [
        "INFO user {u} logged in from {ip}",
        "INFO cache miss for key {k}",
        "WARN disk usage {n}% on /dev/sda1",
        "DEBUG heartbeat from {h}",
        "INFO job {k} finished in {n}s",
        "ERROR request {k} failed with status {n}",
    ]
    new_messages = ["ERROR database connection lost to replica-{h}", "WARN queue depth exceeded limit {n}"]
    gone_messages = ["INFO legacy sync completed for tenant {h}"]
    spike_message = "INFO cache miss for key {k}"

    def fill(pattern: str) -> str:
        return pattern.format(
            u=rng.choice(["alice", "bob", "carol"]),
            ip=f"10.0.{rng.randrange(9)}.{rng.randrange(1, 250)}",
            k=rng.randrange(10_000),
            n=rng.randrange(1, 99),
            h=rng.choice(["a", "b", "c"]),
        )

    def render(messages: list[str], count: int) -> list[str]:
        return [f"2026-10-04T12:{(i // 60) % 60:02d}:{i % 60:02d}Z {fill(rng.choice(messages))}" for i in range(count)]

    before_lines = render(base + gone_messages, 4000)
    after_lines = render(base, 3000) + render(new_messages, 150) + render([spike_message], 2500)
    rng.shuffle(after_lines)
    before = tmp_path / "before.log"
    after = tmp_path / "after.log"
    before.write_text("\n".join(before_lines) + "\n", encoding="utf-8")
    after.write_text("\n".join(after_lines) + "\n", encoding="utf-8")
    truth = {
        "new": {"database connection lost to <*>", "queue depth exceeded limit <NUM>"},
        "gone": {"legacy sync completed for tenant <*>"},
        "changed": {"cache miss for key <NUM>"},
    }
    return before, after, truth


@pytest.mark.parametrize("engine", [pytest.param("native", marks=requires_native), "python"])
def test_diff_finds_injected_changes(tmp_path: Path, engine: str) -> None:
    before, after, truth = synthetic_pair(tmp_path, 3)
    result = logfold.diff(str(before), str(after), format="app", engine=engine)
    assert {e.text for e in result.new_templates} == truth["new"]
    assert {e.text for e in result.disappeared} == truth["gone"]
    assert truth["changed"] <= {e.text for e in result.changed}
    assert {e.text for e in result.new_alerts} == truth["new"]
    assert result.before.records == 4000
    assert result.after.records == 5650


def test_diff_is_symmetric_under_swapping_runs(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 5)
    forward = logfold.diff(str(before), str(after), format="app")
    backward = logfold.diff(str(after), str(before), format="app")
    assert {e.text for e in forward.new_templates} == {e.text for e in backward.disappeared}
    assert {e.text for e in forward.disappeared} == {e.text for e in backward.new_templates}
    assert {e.text for e in forward.changed} == {e.text for e in backward.changed}


def test_diff_identical_inputs_reports_nothing(tmp_path: Path) -> None:
    before, _after, _truth = synthetic_pair(tmp_path, 7)
    result = logfold.diff(str(before), str(before), format="app")
    assert (result.new_templates, result.disappeared, result.changed) == ((), (), ())
    assert result.unchanged > 0


def test_diff_with_token_subset_matcher(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 9)
    result = logfold.diff(str(before), str(after), format="app", matcher="token_subset")
    assert result.config.matcher == "token_subset"


def test_unknown_matcher_is_a_config_error(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 1)
    with pytest.raises(logfold.ConfigError):
        logfold.diff(str(before), str(after), format="app", matcher="nope")


def test_diff_warns_about_nothing_parsed(tmp_path: Path) -> None:
    before, _after, _truth = synthetic_pair(tmp_path, 2)
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    result = logfold.diff(str(before), str(empty), format="app")
    assert any("no records" in w for w in result.warnings)
    assert len(result.disappeared) > 0
