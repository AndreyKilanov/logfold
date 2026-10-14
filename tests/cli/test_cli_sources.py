"""Sources on the command line: ``docker:web`` where a path goes, and the ``--source-*`` options."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
import typer.main
from typer.testing import CliRunner

from conftest import requires_native
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def _left(temp: Path) -> list[Path]:
    return list(temp.glob("logfold-source-*"))


def test_analyze_reads_a_source_and_names_it_in_the_result(fake_source: Path) -> None:
    result = runner.invoke(app, ["analyze", "fake:ok", "-f", "app", "--json"])
    assert result.exit_code == exit_codes.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["run"]["name"] == "fake:ok"
    assert payload["run"]["records"] == 50
    assert "read " in result.stderr
    assert "from fake:ok" in result.stderr
    assert _left(fake_source) == []


def test_a_source_and_a_file_can_form_one_run(fake_source: Path, tmp_path: Path) -> None:
    log = tmp_path / "plain.log"
    log.write_text("2026-10-14 11:00:00 INFO request 1 served in 5 ms\n")
    result = runner.invoke(app, ["analyze", "fake:ok", str(log), "-f", "app", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["run"]["records"] == 51
    assert payload["run"]["name"].startswith("fake:ok,")


def test_diff_compares_two_sources_and_a_source_with_a_file(fake_source: Path, tmp_path: Path) -> None:
    same = runner.invoke(app, ["diff", "fake:ok", "fake:ok", "-f", "app", "--fail-on-new", "-q"])
    assert same.exit_code == exit_codes.OK, same.output
    other = tmp_path / "other.log"
    other.write_text("2026-10-14 11:00:00 ERROR disk full on volume 3\n")
    changed = runner.invoke(app, ["diff", "fake:ok", str(other), "-f", "app", "--fail-on-new", "-q"])
    assert changed.exit_code == exit_codes.NEW_TEMPLATES, changed.output
    assert _left(fake_source) == []


def test_diff_takes_a_source_as_a_baseline(fake_source: Path, tmp_path: Path) -> None:
    same = tmp_path / "same.log"
    same.write_text("2026-10-14 11:00:00 INFO request 1 served in 5 ms\n")
    result = runner.invoke(app, ["diff", str(same), str(same), "--baseline", "fake:ok", "-f", "app", "-q"])
    assert result.exit_code == exit_codes.OK, result.output


def test_learn_and_check_work_on_sources(fake_source: Path, tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    learned = runner.invoke(app, ["learn", "fake:ok", "--state", str(model), "-f", "app", "-q"])
    assert learned.exit_code == exit_codes.OK, learned.output
    checked = runner.invoke(app, ["check", "fake:ok", "--state", str(model), "-f", "app", "-q"])
    assert checked.exit_code == exit_codes.OK, checked.output
    unknown = runner.invoke(app, ["check", "fake:args", "--state", str(model), "-f", "app", "-q"])
    assert unknown.exit_code == exit_codes.CHECK_FAILED, unknown.output


def test_match_works_on_a_source(fake_source: Path, tmp_path: Path) -> None:
    model = tmp_path / "model.json"
    runner.invoke(app, ["learn", "fake:ok", "--state", str(model), "-f", "app", "-q"])
    result = runner.invoke(app, ["match", str(model), "fake:ok", "-f", "app", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(result.stdout)["run"]["name"] == "fake:ok"


def test_inspect_shows_the_source_and_not_the_temporary_file(fake_source: Path) -> None:
    result = runner.invoke(app, ["inspect", "fake:ok", "--json"])
    assert result.exit_code == exit_codes.OK, result.output
    payload = json.loads(result.stdout)
    assert payload["path"] == "fake:ok"
    assert payload["format"] == "app"
    assert _left(fake_source) == []


def test_a_failing_program_is_an_error_and_leaves_nothing_behind(fake_source: Path) -> None:
    result = runner.invoke(app, ["analyze", "fake:fail", "-f", "app"])
    assert result.exit_code == exit_codes.ERROR
    assert "exit code 3" in result.output
    assert _left(fake_source) == []


def test_the_time_limit_is_an_option(fake_source: Path) -> None:
    result = runner.invoke(app, ["analyze", "fake:sleep", "-f", "app", "--source-timeout", "1"])
    assert result.exit_code == exit_codes.ERROR
    assert "did not finish in 1 s" in result.output
    assert "--source-timeout" in result.output
    assert _left(fake_source) == []


def test_the_size_limit_is_an_option(fake_source: Path) -> None:
    result = runner.invoke(app, ["analyze", "fake:big", "-f", "plain", "--source-max-mb", "1"])
    assert result.exit_code == exit_codes.ERROR
    assert "larger than 1 MiB" in result.output
    assert "--source-tail" in result.output
    assert _left(fake_source) == []


def test_source_options_without_a_source_are_an_error(fake_source: Path, tmp_path: Path) -> None:
    log = tmp_path / "a.log"
    log.write_text("2026-10-14 11:00:00 INFO a\n")
    for flag in (["--source-tail", "10"], ["--source-since", "15m"], ["--source-previous"]):
        result = runner.invoke(app, ["analyze", str(log), "-f", "app", *flag])
        assert result.exit_code == exit_codes.ERROR, flag
        assert "need a source such as docker:web" in result.output


def test_an_unknown_source_name_is_just_a_missing_file(fake_source: Path) -> None:
    result = runner.invoke(app, ["analyze", "nosuch:web", "-f", "app"])
    assert result.exit_code == exit_codes.ERROR
    assert "cannot read 'nosuch:web'" in result.output


@pytest.mark.skipif(sys.platform == "win32", reason="a colon is not allowed in a Windows file name")
def test_a_file_with_the_name_of_a_source_is_read_as_a_file_with_a_folder_prefix(
    fake_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fake:ok").write_text("2026-10-14 11:00:00 INFO from a file\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["analyze", "./fake:ok", "-f", "app", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(result.stdout)["run"]["records"] == 1


@pytest.mark.skipif(sys.platform == "win32", reason="a colon is not allowed in a Windows file name")
def test_a_file_that_has_the_name_of_a_source_is_not_run_by_mistake(
    fake_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "fake:ok").write_text("2026-10-14 11:00:00 INFO from a file\n")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["analyze", "fake:ok", "-f", "app"])
    assert result.exit_code == exit_codes.ERROR
    assert "is both a file in this folder and a source" in result.output
    assert "./fake:ok" in result.output


@pytest.mark.parametrize("command", ["analyze", "learn", "check", "match", "diff", "inspect"])
def test_every_command_that_reads_a_log_has_the_source_options_in_the_input_panel(command: str) -> None:
    group: Any = typer.main.get_command(app)
    flags = {
        flag: param.rich_help_panel
        for param in group.commands[command].params
        for flag in param.opts
        if flag.startswith("--source-")
    }
    assert flags == {
        "--source-tail": "Input",
        "--source-since": "Input",
        "--source-previous": "Input",
        "--source-timeout": "Input",
        "--source-max-mb": "Input",
    }
