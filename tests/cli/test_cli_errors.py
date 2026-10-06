from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app

runner = CliRunner()


@pytest.fixture
def free_text(tmp_path: Path) -> Path:
    path = tmp_path / "free.txt"
    path.write_text("just some words here\n" * 30, encoding="utf-8")
    return path


def hint_line(stderr: str) -> str:
    lines = [line for line in stderr.splitlines() if line.startswith("hint:")]
    assert len(lines) == 1, stderr
    return lines[0]


def test_undetected_format_names_the_options_to_try(free_text: Path) -> None:
    result = runner.invoke(app, ["analyze", str(free_text)])
    assert result.exit_code == exit_codes.ERROR
    assert "could not detect the log format" in result.stderr
    hint = hint_line(result.stderr)
    assert "-f plain" in hint
    assert "-f regex:<pattern>" in hint
    assert "logfold formats" in hint


def test_a_long_path_is_not_wrapped(tmp_path: Path) -> None:
    deep = tmp_path.joinpath(*["a-rather-long-folder-name"] * 6)
    result = runner.invoke(app, ["analyze", str(deep / "app.log"), "-f", "plain"])
    assert f"'{deep / 'app.log'}'" in result.stderr


def test_unknown_format_suggests_the_closest_name() -> None:
    result = runner.invoke(app, ["analyze", "x.log", "-f", "nginxx"])
    assert result.exit_code == exit_codes.ERROR
    assert "unknown format 'nginxx'" in result.stderr
    hint = hint_line(result.stderr)
    assert "did you mean 'nginx'?" in hint
    assert "logfold formats" in hint


def test_unknown_format_without_a_close_name_points_to_the_list() -> None:
    result = runner.invoke(app, ["analyze", "x.log", "-f", "zzzzzz"])
    assert "run 'logfold formats'" in hint_line(result.stderr)
    assert "did you mean" not in result.stderr


def test_unknown_reporter_suggests_the_closest_name(free_text: Path) -> None:
    result = runner.invoke(app, ["analyze", str(free_text), "-f", "plain", "--report", "markdwon"])
    assert result.exit_code == exit_codes.ERROR
    hint = hint_line(result.stderr)
    assert "did you mean 'markdown'?" in hint
    assert "logfold plugins list" in hint


def test_unknown_matcher_suggests_the_closest_name(free_text: Path) -> None:
    result = runner.invoke(app, ["diff", str(free_text), str(free_text), "-f", "plain", "--matcher", "jacard"])
    assert result.exit_code == exit_codes.ERROR
    assert "did you mean 'jaccard'?" in hint_line(result.stderr)


@pytest.mark.parametrize("name", ["report", "report.xyz"])
def test_out_without_a_known_suffix_lists_the_suffixes(free_text: Path, tmp_path: Path, name: str) -> None:
    result = runner.invoke(app, ["analyze", str(free_text), "-f", "plain", "-o", str(tmp_path / name)])
    assert result.exit_code == exit_codes.ERROR
    assert "cannot choose a report format" in result.stderr
    hint = hint_line(result.stderr)
    assert ".html" in hint
    assert "--report NAME" in hint
    assert not (tmp_path / name).exists()


def test_missing_file_is_one_short_sentence(tmp_path: Path) -> None:
    missing = tmp_path / "missing.log"
    result = runner.invoke(app, ["analyze", str(missing), "-f", "plain"])
    assert result.exit_code == exit_codes.ERROR
    assert result.stderr.count(str(missing)) == 1
    assert "[Errno" not in result.stderr
    assert "\\\\" not in result.stderr
    assert "no such file" in result.stderr


def test_diff_missing_file_names_the_file(free_text: Path, tmp_path: Path) -> None:
    missing = tmp_path / "gone.log"
    result = runner.invoke(app, ["diff", str(free_text), str(missing), "-f", "plain"])
    assert result.exit_code == exit_codes.ERROR
    assert f"cannot read '{missing}'" in result.stderr


@pytest.mark.parametrize(
    ("flag", "value", "valid"),
    [("--engine", "fast", "auto, native or python"), ("--strategy", "wide", "auto, sequential or chunked")],
)
def test_unknown_engine_or_strategy_lists_the_valid_values(free_text: Path, flag: str, value: str, valid: str) -> None:
    result = runner.invoke(app, ["analyze", str(free_text), "-f", "plain", flag, value])
    assert result.exit_code == exit_codes.ERROR
    assert f"unknown {flag[2:]} '{value}'; use {valid}" in result.stderr


def test_markup_in_a_path_is_shown_literally(tmp_path: Path) -> None:
    missing = tmp_path / "[bold red]x[/].log"
    result = runner.invoke(app, ["analyze", str(missing), "-f", "plain"])
    assert result.exit_code == exit_codes.ERROR
    assert f"'{missing}'" in result.stderr


def test_control_characters_in_a_name_are_not_executed() -> None:
    result = runner.invoke(app, ["analyze", "x.log", "-f", "evil\x1b]0;pwn\x07"])
    assert "\x1b" not in result.stderr
    assert "\\x1b" in result.stderr


def test_debug_still_shows_the_traceback(free_text: Path) -> None:
    result = runner.invoke(app, ["analyze", str(free_text), "--debug"])
    assert result.exit_code != exit_codes.OK
    assert result.exception is not None
    assert "hint:" not in result.stderr
