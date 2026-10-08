"""``match()``: records are assigned to the templates of a saved state and nothing is learned."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, StateError

pytestmark = requires_native

SCHEMA = Path(__file__).parents[2] / "docs" / "schema" / "analysis-v1.schema.json"
LONG = "2026-10-04T00:00:00Z INFO " + " ".join(f"w{i % 3}" for i in range(40))
STRANGE = [LONG] * 3 + ["2026-10-04T00:00:00Z INFO x"]


def trained(tmp_path: Path, lines: list[str]) -> Path:
    log = write(tmp_path / "trained.log", lines)
    logfold.analyze(str(log), format="app", strategy="sequential", save_state=tmp_path / "state.json")
    return tmp_path / "state.json"


def matched(state: Path, log: Path, **options: object) -> logfold.AnalysisResult:
    return logfold.match(state, str(log), format="app", **options)  # type: ignore[arg-type]


def test_the_trained_log_matches_entirely(tmp_path: Path) -> None:
    lines = app_lines(2000, 3)
    state = trained(tmp_path, lines)
    result = matched(state, tmp_path / "trained.log")
    assert result.run.records == 2000
    assert sum(template.count for template in result.templates) == 2000
    assert result.run.unmatched == logfold.Unmatched(records=0, by_length=())
    assert not any("belong to no template" in warning for warning in result.warnings)


def test_records_of_another_shape_are_counted_by_length_and_not_kept(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(1500, 3))
    fresh = write(tmp_path / "fresh.log", app_lines(300, 9) + STRANGE)
    result = matched(state, fresh)
    assert result.run.records == 304
    assert result.run.unmatched is not None
    assert result.run.unmatched.records == 4
    assert [length for length, _ in result.run.unmatched.by_length] == sorted(
        length for length, _ in result.run.unmatched.by_length
    )
    assert sum(template.count for template in result.templates) + result.run.unmatched.records == result.run.records
    assert result.run.unmatched.by_length == ((1, 1), (40, 3))
    assert any("4 of 304 records" in warning for warning in result.warnings)
    assert all("w0" not in template.text for template in result.templates)


def test_the_state_file_is_only_read(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(1500, 3))
    before = state.read_bytes()
    matched(state, write(tmp_path / "fresh.log", app_lines(300, 9) + STRANGE))
    assert state.read_bytes() == before


def test_the_answer_does_not_depend_on_the_strategy(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(1500, 3))
    fresh = write(tmp_path / "fresh.log", app_lines(6000, 9) + STRANGE)
    one = matched(state, fresh, strategy="sequential")
    many = matched(state, fresh, strategy="chunked", threads=3, chunk_bytes=64 * 1024)
    assert many.metrics.strategy == "chunked"
    assert many.metrics.chunks > 1
    assert [(t.id, t.count) for t in many.templates] == [(t.id, t.count) for t in one.templates]
    assert many.run.unmatched == one.run.unmatched
    assert many.run.records == one.run.records


def test_a_time_window_limits_the_records(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(1500, 3))
    fresh = write(tmp_path / "fresh.log", app_lines(1000, 3))
    whole = matched(state, fresh)
    part = matched(state, fresh, since="2026-10-04T00:05:00Z")
    assert part.run.records < whole.run.records
    assert part.run.out_of_range == whole.run.records - part.run.records


def test_the_result_with_unmatched_records_is_valid_json_and_loads_back(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(1500, 3))
    result = matched(state, write(tmp_path / "fresh.log", app_lines(300, 9) + STRANGE))
    document = json.loads(result.to_json())
    jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text(encoding="utf-8"))).validate(document)
    assert document["run"]["unmatched"]["records"] == 4
    result.save(tmp_path / "matched.json")
    assert logfold.load_analysis(tmp_path / "matched.json").run.unmatched == result.run.unmatched


def test_a_mined_result_has_no_unmatched_field(tmp_path: Path) -> None:
    result = logfold.analyze(str(write(tmp_path / "a.log", app_lines(200, 3))), format="app")
    assert result.run.unmatched is None
    assert "unmatched" not in json.loads(result.to_json())["run"]


def test_settings_other_than_the_ones_of_the_state_are_refused(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(500, 3))
    log = write(tmp_path / "fresh.log", app_lines(100, 9))
    with pytest.raises(StateError, match="other masks or parameters"):
        matched(state, log, sim_th=0.7)
    with pytest.raises(StateError, match="other masks or parameters"):
        matched(state, log, masks=[])


def test_a_missing_state_file_is_a_state_error(tmp_path: Path) -> None:
    log = write(tmp_path / "fresh.log", app_lines(10, 9))
    with pytest.raises(StateError, match=r"missing\.json"):
        matched(tmp_path / "missing.json", log)


def test_no_input_is_a_config_error(tmp_path: Path) -> None:
    state = trained(tmp_path, app_lines(100, 3))
    with pytest.raises(ConfigError, match="at least one input"):
        logfold.match(state, [])
