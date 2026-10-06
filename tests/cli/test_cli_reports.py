from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
from corpora import synthetic_pair
from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.cli.output import printable
from logfold.cli.runtime import emit
from logfold.ext import registry

runner = CliRunner()


class AnalysisOnly:
    name = "analysis-only"
    kinds = ("analysis",)

    def render(self, result: object, **options: object) -> str:
        return "analysis only"


def log_file(tmp_path: Path) -> Path:
    before, _after, _truth = synthetic_pair(tmp_path, 6)
    return before


def test_report_name_overrides_the_suffix(tmp_path: Path) -> None:
    out = tmp_path / "result.dat"
    result = runner.invoke(
        app, ["analyze", str(log_file(tmp_path)), "-f", "app", "-o", str(out), "--report", "csv", "-q"]
    )
    assert result.exit_code == 0, result.output
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert "count" in header
    assert "," in header


def test_report_without_out_replaces_the_tables(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file(tmp_path)), "-f", "app", "--report", "markdown"])
    assert result.exit_code == 0, result.output
    assert "|" in result.stdout
    assert result.stdout.startswith("# ")
    csv = runner.invoke(app, ["analyze", str(log_file(tmp_path)), "-f", "app", "--report", "csv"])
    assert csv.stdout.splitlines()[0].count(",") >= 2


def test_report_json_on_stdout_is_valid(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file(tmp_path)), "-f", "app", "--report", "json"])
    assert json.loads(result.stdout)["kind"] == "analysis"


def test_suffixes_pick_csv_and_markdown(tmp_path: Path) -> None:
    source = log_file(tmp_path)
    csv, md = tmp_path / "r.csv", tmp_path / "r.md"
    for target in (csv, md):
        assert runner.invoke(app, ["analyze", str(source), "-f", "app", "-o", str(target), "-q"]).exit_code == 0
    assert csv.read_text(encoding="utf-8").splitlines()[0].count(",") >= 2
    assert "|" in md.read_text(encoding="utf-8")


def test_diff_accepts_report_names(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 8)
    out = tmp_path / "diff.txt"
    result = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "-o", str(out), "--report", "csv", "-q"])
    assert result.exit_code == 0, result.output
    assert "," in out.read_text(encoding="utf-8").splitlines()[0]
    on_stdout = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--report", "markdown"])
    assert on_stdout.exit_code == 0
    assert "|" in on_stdout.stdout


def test_unknown_reporter_fails_before_reading_the_input(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path / "missing.log"), "--report", "nope"])
    assert result.exit_code == exit_codes.ERROR
    assert "unknown reporter" in result.output
    assert "csv" in result.output
    assert "missing.log" not in result.output


def test_reporter_must_support_the_kind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(registry._reporters, "analysis-only", AnalysisOnly())
    source = log_file(tmp_path)
    ok = runner.invoke(app, ["analyze", str(source), "-f", "app", "--report", "analysis-only"])
    assert ok.exit_code == 0
    assert "analysis only" in ok.stdout
    before, after, _truth = synthetic_pair(tmp_path, 4)
    bad = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--report", "analysis-only"])
    assert bad.exit_code == exit_codes.ERROR
    assert "does not support diff" in bad.output


def test_json_and_report_conflict(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file(tmp_path)), "-f", "app", "--json", "--report", "csv"])
    assert result.exit_code == exit_codes.ERROR
    assert "cannot be combined" in result.output


def test_unknown_suffix_mentions_the_report_option(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file(tmp_path)), "-f", "app", "-o", str(tmp_path / "r.xyz")])
    assert result.exit_code == exit_codes.ERROR
    assert "--report" in result.output
    assert not (tmp_path / "r.xyz").exists()


def test_text_report_on_stdout_honours_top(tmp_path: Path) -> None:
    source = log_file(tmp_path)
    full = runner.invoke(app, ["analyze", str(source), "-f", "app", "--report", "text", "--top", "3"])
    assert full.exit_code == 0
    assert len(full.stdout.splitlines()) < 12


class Boom:
    name = "boom"
    kinds = ("analysis", "diff")

    def render(self, result: object, **options: object) -> str:
        raise ValueError("plugin exploded")


class NoText:
    name = "notext"
    kinds = ("analysis", "diff")

    def render(self, result: object, **options: object) -> None:
        return None


@pytest.mark.parametrize(("reporter", "message"), [("boom", "plugin exploded"), ("notext", "expected text")])
def test_failing_plugin_reporter_is_a_clean_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reporter: str, message: str
) -> None:
    monkeypatch.setitem(registry._reporters, "boom", Boom())
    monkeypatch.setitem(registry._reporters, "notext", NoText())
    source = log_file(tmp_path)
    on_stdout = runner.invoke(app, ["analyze", str(source), "-f", "app", "--report", reporter])
    assert on_stdout.exit_code == exit_codes.ERROR
    assert message in on_stdout.output
    assert "Traceback" not in on_stdout.output
    out = tmp_path / "report.dat"
    to_file = runner.invoke(app, ["analyze", str(source), "-f", "app", "--report", reporter, "-o", str(out)])
    assert to_file.exit_code == exit_codes.ERROR
    assert "Traceback" not in to_file.output
    assert not out.exists()


def test_printable_shows_control_characters() -> None:
    assert printable("a\tb\nc") == "a\tb\nc"
    assert printable("\x1b]0;x\x07\x1b[31m") == r"\x1b]0;x\x07\x1b[31m"
    assert printable("\x9b\x00\r") == r"\x9b\x00\x0d"
    assert printable("привет, café 😀") == "привет, café 😀"


class FakeTerminal(io.StringIO):
    def isatty(self) -> bool:
        return True


def hostile_result(tmp_path: Path) -> logfold.AnalysisResult:
    log = tmp_path / "hostile.log"
    line = "2026-10-04T12:00:00Z INFO agent \x1b]0;pwned\x07\x1b[31mred done\n"
    log.write_text(line * 3, encoding="utf-8")
    return logfold.analyze(str(log), format="app")


@pytest.mark.parametrize("reporter", ["text", "markdown", "csv", "json"])
def test_terminal_output_never_carries_escape_sequences(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reporter: str
) -> None:
    terminal = FakeTerminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    emit(hostile_result(tmp_path), 20, reporter)
    output = terminal.getvalue()
    assert "\x1b" not in output
    assert "\x07" not in output


def test_default_tables_never_carry_escape_sequences(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    terminal = FakeTerminal()
    monkeypatch.setattr(sys, "stdout", terminal)
    emit(hostile_result(tmp_path), 20, None)
    assert "\x1b]" not in terminal.getvalue()
    assert r"\x1b]" in terminal.getvalue()
    assert r";pwned\x07\x1b[31m" in terminal.getvalue()


def test_redirected_output_keeps_the_raw_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    pipe = io.StringIO()
    monkeypatch.setattr(sys, "stdout", pipe)
    emit(hostile_result(tmp_path), 20, "csv")
    assert "\x1b]" in pipe.getvalue()
