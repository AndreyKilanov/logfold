"""``logfold match``: the records of a log against a saved state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import requires_native
from corpora import app_lines, write
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})
STRANGE = ["2026-10-04T00:00:00Z INFO " + " ".join(f"w{i % 3}" for i in range(40))] * 3


@pytest.fixture
def state(tmp_path: Path) -> Path:
    log = write(tmp_path / "trained.log", app_lines(1500, 3))
    result = runner.invoke(app, ["analyze", str(log), "-f", "app", "--save-state", str(tmp_path / "s.json"), "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    return tmp_path / "s.json"


def test_match_prints_the_templates_and_says_how_many_records_fit_none(state: Path, tmp_path: Path) -> None:
    fresh = write(tmp_path / "fresh.log", app_lines(200, 9) + STRANGE)
    result = runner.invoke(app, ["match", str(state), str(fresh), "-f", "app"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "3 of 203 records" in result.output
    assert "belong to no template of the state" in result.output
    assert "logged in from" in result.output


def test_json_output_carries_the_unmatched_records_and_the_state_is_not_touched(state: Path, tmp_path: Path) -> None:
    before = state.read_bytes()
    fresh = write(tmp_path / "fresh.log", app_lines(200, 9) + STRANGE)
    result = runner.invoke(app, ["match", str(state), str(fresh), "-f", "app", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(result.output)["run"]["unmatched"] == {"records": 3, "by_length": [[40, 3]]}
    assert state.read_bytes() == before


def test_a_report_file_can_be_written(state: Path, tmp_path: Path) -> None:
    fresh = write(tmp_path / "fresh.log", app_lines(200, 9))
    out = tmp_path / "matched.json"
    result = runner.invoke(app, ["match", str(state), str(fresh), "-f", "app", "-o", str(out), "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["run"]["unmatched"]["records"] == 0


def test_settings_of_another_state_are_refused_with_the_error_exit_code(state: Path, tmp_path: Path) -> None:
    fresh = write(tmp_path / "fresh.log", app_lines(50, 9))
    result = runner.invoke(app, ["match", str(state), str(fresh), "-f", "app", "--sim-th", "0.8"])
    assert result.exit_code == exit_codes.ERROR
    assert "other masks or parameters" in result.output


def test_a_missing_state_is_an_error_not_a_traceback(tmp_path: Path) -> None:
    fresh = write(tmp_path / "fresh.log", app_lines(50, 9))
    result = runner.invoke(app, ["match", str(tmp_path / "nope.json"), str(fresh), "-f", "app"])
    assert result.exit_code == exit_codes.ERROR
    assert "nope.json" in result.output
    assert "Traceback" not in result.output


def test_the_help_lists_the_command_and_not_the_training_options() -> None:
    top = runner.invoke(app, ["--help"])
    assert "match" in top.output
    result = runner.invoke(app, ["match", "--help"])
    assert result.exit_code == exit_codes.OK
    assert "STATE" in result.output
    for option in ("--load-state", "--high-cardinality", "--warm-start", "--engine"):
        assert option not in result.output
