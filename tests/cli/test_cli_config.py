"""``logfold.toml`` on the command line: found, named, switched off, and weaker than a flag."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.main import get_command
from typer.testing import CliRunner

from conftest import requires_native
from corpora import app_lines, write
from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.config import DiffConfig

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture(autouse=True)
def quiet_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LOGFOLD_CONFIG", raising=False)


@pytest.fixture
def folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    write(tmp_path / "a.log", app_lines(600, 3))
    return tmp_path


def settings(folder: Path, text: str, name: str = "logfold.toml") -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def rows(output: str) -> int:
    return sum(1 for line in output.splitlines() if line.strip()[:1].isdigit())


def test_the_file_in_the_current_folder_is_used_and_named_on_stderr(folder: Path) -> None:
    settings(folder, 'format = "app"\n[output]\ntop = 2\n')
    result = runner.invoke(app, ["analyze", "a.log"])
    assert result.exit_code == exit_codes.OK, result.output
    assert f"config: {folder / 'logfold.toml'}" in result.output
    assert "format app" in result.output
    assert rows(result.output) == 2


def test_quiet_keeps_the_note_out(folder: Path) -> None:
    settings(folder, 'format = "app"\n')
    result = runner.invoke(app, ["analyze", "a.log", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "config:" not in result.output


def test_a_flag_beats_the_file(folder: Path) -> None:
    settings(folder, 'format = "app"\n[output]\ntop = 1\n')
    result = runner.invoke(app, ["analyze", "a.log", "--top", "4"])
    assert rows(result.output) == 4
    other = runner.invoke(app, ["analyze", "a.log", "-f", "plain", "--json", "-q"])
    assert json.loads(other.output)["meta"]["format"] == "plain"


def test_no_config_reads_nothing_and_config_names_a_file(folder: Path) -> None:
    settings(folder, 'format = "app"\n[output]\ntop = 1\n')
    off = runner.invoke(app, ["--no-config", "analyze", "a.log", "-f", "app", "-q"])
    assert off.exit_code == exit_codes.OK, off.output
    assert rows(off.output) > 1
    named = settings(folder, "[output]\ntop = 3\n", "other.toml")
    result = runner.invoke(app, ["--config", str(named), "analyze", "a.log", "-f", "app"])
    assert rows(result.output) == 3
    assert f"config: {named}" in result.output


def test_both_config_options_together_are_refused(folder: Path) -> None:
    named = settings(folder, "")
    result = runner.invoke(app, ["--config", str(named), "--no-config", "analyze", "a.log"])
    assert result.exit_code == exit_codes.ERROR
    assert "exclude each other" in result.output


def test_a_wrong_file_stops_a_command_with_the_error_exit_code_and_a_hint(folder: Path) -> None:
    settings(folder, "[mining]\ndepht = 4\n")
    result = runner.invoke(app, ["analyze", "a.log", "-f", "app"])
    assert result.exit_code == exit_codes.ERROR
    assert "unknown key 'depht' in [mining]" in result.output
    assert "did you mean 'depth'?" in result.output
    assert "Traceback" not in result.output


def test_help_works_whatever_the_file_holds(folder: Path) -> None:
    settings(folder, "this is not toml [")
    for arguments in (["--help"], ["analyze", "--help"], ["diff", "--help"], ["match", "--help"]):
        result = runner.invoke(app, arguments)
        assert result.exit_code == exit_codes.OK, (arguments, result.output)
    options = {opt for param in get_command(app).params for opt in param.opts}  # type: ignore[attr-defined]
    assert {"--config", "--no-config"} <= options


def test_the_masks_of_the_file_reach_the_run(folder: Path) -> None:
    settings(folder, 'format = "app"\n[mining]\nmasks = "none"\n')
    with_file = runner.invoke(app, ["analyze", "a.log", "--json", "-q"])
    without = runner.invoke(app, ["--no-config", "analyze", "a.log", "-f", "app", "--json", "-q"])
    assert json.loads(with_file.output)["meta"]["config_hash"] != json.loads(without.output)["meta"]["config_hash"]
    assert any("<NUM>" in item["text"] for item in json.loads(without.output)["templates"])
    assert not any("<NUM>" in item["text"] for item in json.loads(with_file.output)["templates"])


def test_the_state_of_one_file_is_used_with_the_same_file_and_refused_without_it(folder: Path) -> None:
    settings(folder, 'format = "app"\n[mining]\nsim_th = 0.6\n')
    assert runner.invoke(app, ["analyze", "a.log", "--save-state", "s.json", "-q"]).exit_code == exit_codes.OK
    assert runner.invoke(app, ["match", "s.json", "a.log", "-q"]).exit_code == exit_codes.OK
    refused = runner.invoke(app, ["--no-config", "match", "s.json", "a.log", "-f", "app"])
    assert refused.exit_code == exit_codes.ERROR
    assert "other masks or parameters" in refused.output


def test_diff_options_and_the_exit_code_come_from_the_file(folder: Path) -> None:
    write(folder / "b.log", app_lines(600, 3) + ["2026-10-05T00:00:00Z ERROR brand new failure z9"] * 30)
    plain = runner.invoke(app, ["diff", "a.log", "b.log", "-f", "app", "-q"])
    assert plain.exit_code == exit_codes.OK, plain.output
    settings(folder, 'format = "app"\n[diff]\nfail_on_new = true\n')
    failing = runner.invoke(app, ["diff", "a.log", "b.log", "-q"])
    assert failing.exit_code == exit_codes.NEW_TEMPLATES, failing.output
    settings(folder, 'format = "app"\n[diff]\nmin_new_count = 1000\nfail_on_new = true\n')
    assert runner.invoke(app, ["diff", "a.log", "b.log", "-q"]).exit_code == exit_codes.OK


def test_saved_reports_can_be_compared_while_the_file_names_a_format(folder: Path) -> None:
    for name in ("a", "b"):
        assert runner.invoke(app, ["analyze", "a.log", "-f", "app", "-o", f"{name}.json", "-q"]).exit_code == 0
    settings(folder, 'format = "app"\n[diff]\nrecount = false\n')
    result = runner.invoke(app, ["diff", "a.json", "b.json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    typed = runner.invoke(app, ["diff", "a.json", "b.json", "-f", "app", "-q"])
    assert typed.exit_code == exit_codes.ERROR
    assert "--format" in typed.output


def test_inspect_uses_the_format_of_the_file(folder: Path) -> None:
    settings(folder, 'format = "app"\n')
    result = runner.invoke(app, ["inspect", "a.log"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "app" in result.output


def test_the_defaults_of_the_diff_command_are_those_of_the_library() -> None:
    options = {param.name: param.default for param in get_command(app).commands["diff"].params}  # type: ignore[attr-defined]
    defaults = DiffConfig()
    for name in ("threshold_ratio", "min_count", "min_new_count", "significance", "matcher", "recount"):
        assert options[name] == getattr(defaults, name), name
