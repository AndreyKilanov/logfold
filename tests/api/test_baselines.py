"""Several baselines in diff(): pooling, min_baselines, the unstable templates and the refusals."""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold import ConfigError, DiffConfig

STABLE = 40


def write(path: Path, *parts: str) -> Path:
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def block(count: int, template: str) -> str:
    return "\n".join(template.format(i=i) for i in range(count))


COMMON = "INFO request {i} served from cache in {i} ms"
HEARTBEAT = "INFO worker heartbeat number {i} accepted by the scheduler"
RETRY = "WARN retrying upstream call attempt {i} after connection reset"
CLEANUP = "INFO nightly cleanup removed {i} expired sessions"
CRASH = "ERROR payment gateway rejected order {i} with status 502"


@pytest.fixture
def runs(tmp_path: Path) -> dict[str, Path]:
    """Three baselines and a run after: retry is in two baselines, cleanup in one, the heartbeat is gone."""
    common = block(STABLE, COMMON)
    return {
        "b1": write(tmp_path / "b1.log", common, block(STABLE, HEARTBEAT), block(STABLE, RETRY), block(3, CLEANUP)),
        "b2": write(tmp_path / "b2.log", common, block(STABLE, HEARTBEAT), block(STABLE, RETRY)),
        "b3": write(tmp_path / "b3.log", common, block(STABLE, HEARTBEAT)),
        "after": write(tmp_path / "after.log", common, block(STABLE, RETRY), block(STABLE, CRASH)),
    }


def texts(entries: tuple[logfold.DiffEntry, ...]) -> set[str]:
    return {entry.text for entry in entries}


def result(runs: dict[str, Path], **options: object) -> logfold.DiffResult:
    return logfold.diff(
        runs["b1"],
        runs["after"],
        baselines=[runs["b2"], runs["b3"]],
        format="plain",
        engine="python",
        min_count=1,
        significance=1.0,
        **options,  # type: ignore[arg-type]
    )


def test_new_needs_no_baseline_to_have_it(runs: dict[str, Path]) -> None:
    single = logfold.diff(runs["b3"], runs["after"], format="plain", engine="python", min_count=1)
    assert any("retry" in text for text in texts(single.new_templates))
    pooled = result(runs)
    assert not any("retry" in text for text in texts(pooled.new_templates))
    assert any("payment gateway" in text for text in texts(pooled.new_templates))
    assert len(pooled.new_templates) == 1


def test_a_template_must_be_in_every_baseline_to_disappear_by_default(runs: dict[str, Path]) -> None:
    pooled = result(runs)
    assert any("heartbeat" in text for text in texts(pooled.disappeared))
    assert not any("cleanup" in text for text in texts(pooled.disappeared))


def test_min_baselines_decides_which_templates_count(runs: dict[str, Path]) -> None:
    wide = result(runs, min_baselines=1)
    assert any("cleanup" in text for text in texts(wide.disappeared))
    middle = result(runs, min_baselines=2)
    assert not any("cleanup" in text for text in texts(middle.disappeared))
    assert any("heartbeat" in text for text in texts(middle.disappeared))


def test_a_template_in_too_few_baselines_is_unstable_not_new_or_changed(runs: dict[str, Path]) -> None:
    strict = result(runs)
    both = {entry.text for entry in (*strict.new_templates, *strict.changed)}
    assert not any("retry" in text for text in both)
    assert strict.unchanged == 2


def test_counts_and_records_are_pooled(runs: dict[str, Path]) -> None:
    pooled = result(runs, min_baselines=1)
    singles = [logfold.analyze(runs[name], format="plain", engine="python") for name in ("b1", "b2", "b3")]
    assert pooled.before.records == sum(s.run.records for s in singles)
    assert pooled.before.files == 3
    assert all(str(runs[name]) in pooled.before.name for name in ("b1", "b2", "b3"))
    heartbeat = next(e for e in pooled.disappeared if "heartbeat" in e.text)
    assert heartbeat.before_count == 3 * STABLE
    assert heartbeat.before_share == pytest.approx(3 * STABLE / pooled.before.records)


def test_pooling_with_min_one_equals_the_concatenated_baseline(runs: dict[str, Path], tmp_path: Path) -> None:
    pooled = result(runs, min_baselines=1)
    joined = logfold.diff(
        [runs["b1"], runs["b2"], runs["b3"]],
        runs["after"],
        format="plain",
        engine="python",
        min_count=1,
        significance=1.0,
    )
    assert pooled.new_templates == joined.new_templates
    assert pooled.disappeared == joined.disappeared
    assert pooled.changed == joined.changed
    assert pooled.unchanged == joined.unchanged


def test_one_baseline_and_no_baselines_are_the_same(runs: dict[str, Path]) -> None:
    plain = logfold.diff(runs["b1"], runs["after"], format="plain", engine="python")
    empty = logfold.diff(runs["b1"], runs["after"], baselines=[], format="plain", engine="python")
    assert plain.new_templates == empty.new_templates
    assert plain.changed == empty.changed
    assert plain.unchanged == empty.unchanged
    assert (
        logfold.diff(runs["b1"], runs["after"], min_baselines=1, format="plain", engine="python").changed
        == plain.changed
    )


def test_a_baseline_can_be_several_files(runs: dict[str, Path]) -> None:
    nested = logfold.diff(
        runs["b1"], runs["after"], baselines=[[runs["b2"], runs["b3"]]], format="plain", engine="python", min_count=1
    )
    assert nested.before.files == 3


@requires_native
@pytest.mark.parametrize("minimum", [None, 1, 2])
def test_native_and_python_engines_agree(runs: dict[str, Path], minimum: int | None) -> None:
    python = result(runs, min_baselines=minimum)
    native = logfold.diff(
        runs["b1"],
        runs["after"],
        baselines=[runs["b2"], runs["b3"]],
        format="plain",
        engine="native",
        min_count=1,
        significance=1.0,
        min_baselines=minimum,
    )
    assert native.new_templates == python.new_templates
    assert native.disappeared == python.disappeared
    assert native.changed == python.changed
    assert native.unchanged == python.unchanged
    assert native.before.records == python.before.records


def test_min_baselines_cannot_exceed_the_baselines(runs: dict[str, Path]) -> None:
    with pytest.raises(ConfigError, match="only 3 baselines"):
        result(runs, min_baselines=4)
    with pytest.raises(ConfigError, match="at least 1"):
        DiffConfig(min_baselines=0)


def test_saved_results_and_split_at_refuse_baselines(runs: dict[str, Path]) -> None:
    saved = logfold.analyze(runs["b1"], format="plain")
    with pytest.raises(ConfigError, match="baselines"):
        logfold.diff(saved, saved, baselines=[runs["b2"]])
    with pytest.raises(ConfigError, match="min_baselines"):
        logfold.diff(saved, saved, min_baselines=1)
    with pytest.raises(ConfigError, match="split_at"):
        logfold.diff(runs["b1"], split_at="2026-10-06T00:00:00", baselines=[runs["b2"]], format="plain")


def test_a_time_window_applies_to_every_baseline(tmp_path: Path) -> None:
    lines = [f"2026-10-06T00:00:{i:02d} INFO tick {i} done" for i in range(40)]
    files = []
    for name in ("a", "b"):
        files.append(write(tmp_path / f"{name}.log", *lines))
    after = write(tmp_path / "after.log", *lines)
    spec = r"regex:^(?P<ts>\S+) (?P<lvl>[A-Z]+) (?P<msg>.*)$"
    narrowed = logfold.diff(
        files[0], after, baselines=[files[1]], format=spec, since="2026-10-06T00:00:10", until="2026-10-06T00:00:20"
    )
    assert narrowed.before.records == 20
    assert narrowed.after.records == 10


def test_an_empty_baseline_is_warned_about(runs: dict[str, Path], tmp_path: Path) -> None:
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    pooled = logfold.diff(
        runs["b1"], runs["after"], baselines=[empty], format="plain", engine="python", min_count=1, significance=1.0
    )
    assert any("empty.log has no records" in warning for warning in pooled.warnings)
    quiet = logfold.diff(runs["b1"], runs["after"], baselines=[runs["b2"]], format="plain", engine="python")
    assert not any("no records" in warning for warning in quiet.warnings)
