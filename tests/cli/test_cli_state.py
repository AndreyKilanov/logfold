"""``--save-state``, ``--load-state`` and ``--state-format`` of ``logfold analyze``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import requires_native
from corpora import app_lines, write
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture
def logs(tmp_path: Path) -> tuple[Path, Path, Path]:
    lines = app_lines(2000, 5)
    return (
        write(tmp_path / "all.log", lines),
        write(tmp_path / "a.log", lines[:900]),
        write(tmp_path / "b.log", lines[900:]),
    )


def analyze(*args: str) -> tuple[int, str]:
    result = runner.invoke(app, ["analyze", "-f", "app", "--strategy", "sequential", *args])
    return result.exit_code, result.output


def test_a_state_is_saved_and_the_run_says_so(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    code, output = analyze(str(logs[1]), "--save-state", str(tmp_path / "s.json"))
    assert code == exit_codes.OK, output
    assert "saved the state to" in output
    assert (tmp_path / "s.json").read_bytes().startswith(b'{"kind":"logfold-state"')


def test_quiet_keeps_the_note_out(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    code, output = analyze(str(logs[1]), "--save-state", str(tmp_path / "s.json"), "-q")
    assert code == exit_codes.OK, output
    assert "saved the state" not in output


@pytest.mark.parametrize("form", ["json", "binary"])
def test_a_resumed_run_saves_the_same_bytes_as_an_uninterrupted_one(
    logs: tuple[Path, Path, Path], tmp_path: Path, form: str
) -> None:
    whole, first, second = logs
    assert analyze(str(whole), "--save-state", str(tmp_path / "whole"), "--state-format", form)[0] == exit_codes.OK
    assert analyze(str(first), "--save-state", str(tmp_path / "s"), "--state-format", form)[0] == exit_codes.OK
    code, output = analyze(
        str(second), "--load-state", str(tmp_path / "s"), "--save-state", str(tmp_path / "s2"), "--state-format", form
    )
    assert code == exit_codes.OK, output
    assert (tmp_path / "s2").read_bytes() == (tmp_path / "whole").read_bytes()


def test_the_binary_form_is_chosen_with_the_flag(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    assert analyze(str(logs[1]), "--save-state", str(tmp_path / "s"), "--state-format", "binary")[0] == exit_codes.OK
    assert (tmp_path / "s").read_bytes().startswith(b"LFSTATE\x00")


def test_other_settings_are_refused_with_a_hint(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    assert analyze(str(logs[1]), "--save-state", str(tmp_path / "s.json"))[0] == exit_codes.OK
    code, output = analyze(str(logs[2]), "--load-state", str(tmp_path / "s.json"), "--depth", "6")
    assert code == exit_codes.ERROR
    assert "other masks or parameters" in output
    assert "hint:" in output


def test_a_missing_or_damaged_state_is_an_error(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    code, output = analyze(str(logs[2]), "--load-state", str(tmp_path / "missing.json"))
    assert code == exit_codes.ERROR
    assert "missing.json" in output
    damaged = tmp_path / "damaged.json"
    damaged.write_text("not a state", encoding="utf-8")
    code, output = analyze(str(logs[2]), "--load-state", str(damaged))
    assert code == exit_codes.ERROR
    assert "not a logfold state file" in output


def test_a_chunked_run_cannot_continue_a_state(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    assert analyze(str(logs[1]), "--save-state", str(tmp_path / "s.json"))[0] == exit_codes.OK
    result = runner.invoke(
        app, ["analyze", str(logs[2]), "-f", "app", "--strategy", "chunked", "--load-state", str(tmp_path / "s.json")]
    )
    assert result.exit_code == exit_codes.ERROR
    assert "sequential strategy only" in result.output


def test_an_unknown_state_format_is_an_error(logs: tuple[Path, Path, Path], tmp_path: Path) -> None:
    code, output = analyze(str(logs[1]), "--save-state", str(tmp_path / "s"), "--state-format", "yaml")
    assert code == exit_codes.ERROR
    assert "state_format" in output


def test_the_options_are_in_the_help_panels() -> None:
    output = runner.invoke(app, ["analyze", "--help"]).output
    for flag in ("--load-state", "--save-state", "--state-format"):
        assert flag in output
