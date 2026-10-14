"""``logfold learn`` and ``logfold check``: a model from a good log, and a log against it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from conftest import requires_native
from corpora import app_lines, write
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})
PANIC = ["2026-10-04T00:00:00Z ERROR kernel panic on node n1 while mounting volume"] * 3
HARMLESS = ["2026-10-04T00:00:00Z INFO brand new harmless message appears here today"] * 2


@pytest.fixture
def model(tmp_path: Path) -> Path:
    good = write(tmp_path / "good.log", app_lines(1500, 3))
    result = runner.invoke(app, ["learn", str(good), "--state", str(tmp_path / "model.json"), "-f", "app", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    return tmp_path / "model.json"


def run(model: Path, log: Path, *options: str) -> Result:
    return runner.invoke(app, ["check", str(log), "--state", str(model), "-f", "app", *options])


def test_learn_saves_a_model_and_says_what_it_holds(tmp_path: Path) -> None:
    good = write(tmp_path / "good.log", app_lines(500, 3))
    result = runner.invoke(app, ["learn", str(good), "--state", str(tmp_path / "m.json"), "-f", "app"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "saved the model to" in result.output
    assert (tmp_path / "m.json").is_file()


def test_a_log_like_the_model_passes_with_exit_code_zero(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(300, 7))
    result = run(model, current)
    assert result.exit_code == exit_codes.OK, result.output
    assert "check passed" in result.output


def test_a_finding_gives_exit_code_two_after_the_report_is_written(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(200, 7) + PANIC + HARMLESS)
    out = tmp_path / "check.json"
    before = model.read_bytes()
    result = run(model, current, "-o", str(out), "-q")
    assert result.exit_code == exit_codes.CHECK_FAILED == 2
    assert "check FAILED" in result.output
    assert "kernel panic" in result.output
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["kind"] == "check"
    assert payload["passed"] is False
    assert [finding["kind"] for finding in payload["findings"]] == ["unmatched", "new"]
    assert model.read_bytes() == before


def test_json_goes_to_standard_output(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(200, 7))
    result = run(model, current, "--json", "-q")
    assert result.exit_code == exit_codes.OK
    assert json.loads(result.output)["passed"] is True


def test_the_comparison_reports_work_for_a_check(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(200, 7) + PANIC)
    summary = tmp_path / "summary.md"
    result = run(model, current, "--report", "github-summary", "-o", str(summary), "--append", "-q")
    assert result.exit_code == exit_codes.CHECK_FAILED
    assert "kernel panic" in summary.read_text(encoding="utf-8")


def test_the_limit_and_the_gate_can_be_changed(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(200, 7) + PANIC + HARMLESS)
    assert run(model, current, "--max-unmatched", "off", "--fail-on", "none", "-q").exit_code == exit_codes.OK
    assert run(model, current, "--max-unmatched", "5", "--fail-on", "none", "-q").exit_code == exit_codes.OK
    assert run(model, current, "--max-unmatched", "5", "-q").exit_code == exit_codes.CHECK_FAILED


def test_bad_options_are_errors(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(50, 7))
    for options in (["--max-unmatched", "many"], ["--max-unmatched", "101"], ["--fail-on", "sometimes"]):
        result = run(model, current, *options)
        assert result.exit_code == exit_codes.ERROR, options


def test_a_missing_model_is_an_error(tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(50, 7))
    result = run(tmp_path / "missing.json", current)
    assert result.exit_code == exit_codes.ERROR


def test_the_settings_file_gives_the_defaults(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(200, 7) + PANIC)
    settings = tmp_path / "logfold.toml"
    settings.write_text('[check]\nmax_unmatched = "off"\nfail_on = "none"\n', encoding="utf-8")
    result = runner.invoke(app, ["--config", str(settings), "check", str(current), "--state", str(model), "-f", "app"])
    assert result.exit_code == exit_codes.OK, result.output
    flagged = runner.invoke(
        app, ["--config", str(settings), "check", str(current), "--state", str(model), "-f", "app", "--fail-on", "new"]
    )
    assert flagged.exit_code == exit_codes.CHECK_FAILED, flagged.output


def test_the_level_filter_hides_templates_not_findings(model: Path, tmp_path: Path) -> None:
    current = write(tmp_path / "current.log", app_lines(200, 7) + PANIC + HARMLESS)
    result = run(model, current, "--level", "ERROR")
    assert result.exit_code == exit_codes.CHECK_FAILED
    assert "kernel panic" in result.output
    assert "brand new harmless" not in result.output


def test_the_commands_are_listed_in_the_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert "check" in result.output
    assert "learn" in result.output
