from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from logfold.api.inspecting import inspect_file
from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.errors import FormatError, SourceError

runner = CliRunner()


def test_an_app_log_shows_format_levels_and_records(corpus_dir: Path) -> None:
    found = inspect_file(corpus_dir / "app.log")
    assert found.spec.name == "app"
    assert found.confidence == 1.0
    assert found.records == 1000
    assert found.lines == 1000
    assert found.truncated is True
    assert set(found.levels) == {"DEBUG", "INFO", "WARN", "ERROR"}
    assert sum(found.levels.values()) + found.no_level == found.records
    assert found.first_time is not None
    assert found.last_time is not None
    assert found.first_time <= found.last_time
    assert len(found.shown) == 10
    assert found.shown[0].level is not None
    assert found.shown[0].time == found.first_time


def test_the_sample_and_the_shown_records_are_limited(corpus_dir: Path) -> None:
    found = inspect_file(corpus_dir / "app.log", limit=3, sample_lines=50)
    assert len(found.shown) == 3
    assert found.lines == 50
    assert found.records == 50
    assert found.truncated is True
    whole = inspect_file(corpus_dir / "app.log", sample_lines=10_000)
    assert whole.truncated is False
    assert whole.records == 1500


def test_multiline_records_count_their_lines(corpus_dir: Path) -> None:
    found = inspect_file(corpus_dir / "multiline.log", sample_lines=10_000)
    assert found.multiline_auto is True
    assert found.spec.multiline is True
    assert found.unparsed == 0
    assert any(record.lines > 1 for record in found.shown)
    assert found.lines > found.records


def test_unparsed_lines_are_counted(corpus_dir: Path) -> None:
    found = inspect_file(corpus_dir / "jsonl.log", sample_lines=10_000)
    assert found.spec.name == "jsonl"
    assert found.unparsed > 0
    assert found.records + found.unparsed == found.lines


def test_a_gzip_file_is_read_and_marked(tmp_path: Path) -> None:
    path = tmp_path / "app.log.gz"
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("2026-10-04T00:00:00Z ERROR boom\n2026-10-04T00:00:01Z INFO fine\n" * 30)
    found = inspect_file(path)
    assert found.compressed is True
    assert found.records == 60
    assert found.levels == {"INFO": 30, "ERROR": 30}


def test_an_empty_file_is_plain_with_no_records(tmp_path: Path) -> None:
    path = tmp_path / "empty.log"
    path.write_bytes(b"")
    found = inspect_file(path)
    assert found.spec.name == "plain"
    assert found.records == 0
    assert found.shown == ()
    assert found.first_time is None


def test_a_regex_format_is_applied(tmp_path: Path) -> None:
    path = tmp_path / "x.log"
    path.write_text("A first\nB second\n", encoding="utf-8")
    found = inspect_file(path, format=r"regex:^(?P<level>[AB]) (?P<message>.*)")
    assert found.confidence is None
    assert [record.message for record in found.shown] == ["first", "second"]


def test_missing_standard_input_and_unknown_format_are_errors(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="no such file"):
        inspect_file(tmp_path / "missing.log", format="plain")
    with pytest.raises(FormatError):
        inspect_file(tmp_path / "missing.log", format="nope")


def test_the_command_prints_a_summary_and_a_table(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["inspect", str(corpus_dir / "app.log"), "-n", "3"], env={"COLUMNS": "120"})
    assert result.exit_code == exit_codes.OK, result.output
    assert "format     app (auto-detected, 100% of the sample)" in result.stdout
    assert "(the file continues)" in result.stdout
    assert "levels     ERROR" in result.stdout
    assert "message" in result.stdout
    assert result.stdout.count("T00:") + result.stdout.count("-10-04 00:") >= 3


def test_the_command_hints_when_the_format_has_no_levels(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["inspect", str(corpus_dir / "nginx.log")])
    assert result.exit_code == exit_codes.OK
    assert "--level and --only-alerts have nothing to filter by" in result.stdout


def test_the_command_hints_when_many_lines_do_not_parse(corpus_dir: Path) -> None:
    result = runner.invoke(
        app, ["inspect", str(corpus_dir / "app.log"), "-f", r"regex:^(?P<message>NEVER)", "--multiline"]
    )
    assert result.exit_code == exit_codes.OK
    assert "did not parse; try -f plain" in result.stdout


def test_the_json_output_is_valid_and_complete(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["inspect", str(corpus_dir / "app.log"), "--json", "-n", "2"])
    assert result.exit_code == exit_codes.OK
    payload = json.loads(result.stdout)
    assert payload["kind"] == "inspection"
    assert payload["schema_version"] == 1
    assert payload["format"] == "app"
    assert len(payload["shown"]) == 2
    assert set(payload["levels"]) <= {"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"}


def test_standard_input_is_refused_with_a_hint() -> None:
    result = runner.invoke(app, ["inspect", "-"])
    assert result.exit_code == exit_codes.ERROR
    assert "needs a file, not standard input" in result.stderr
    assert "head -n 1000" in result.stderr


def test_a_missing_file_and_an_undetected_format_are_clean_errors(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["inspect", str(tmp_path / "missing.log"), "-f", "plain"])
    assert missing.exit_code == exit_codes.ERROR
    assert "cannot read" in missing.stderr
    free = tmp_path / "free.txt"
    free.write_text("just some words here\n" * 30, encoding="utf-8")
    undetected = runner.invoke(app, ["inspect", str(free)])
    assert undetected.exit_code == exit_codes.ERROR
    assert "-f plain" in undetected.stderr


def test_hostile_content_cannot_drive_the_terminal(tmp_path: Path) -> None:
    path = tmp_path / "evil.log"
    path.write_text("2026-10-04T00:00:00Z INFO \x1b]0;pwn\x07 [bold red]x[/] hello\n" * 5, encoding="utf-8")
    result = runner.invoke(app, ["inspect", str(path), "-f", "app"])
    assert result.exit_code == exit_codes.OK
    assert "\x1b" not in result.stdout
    assert "\x07" not in result.stdout
    assert "[bold red]x[/]" in result.stdout
