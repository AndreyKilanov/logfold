"""A report file has line feeds only, on every platform: the Prometheus text format does not allow a carriage return."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import logfold
from corpora import hostile_pair
from logfold.ext.files import write_text
from logfold.model import AnalysisResult, DiffResult

CARRIAGE_RETURN = b"\r"
DIFF_REPORTERS = ("text", "markdown", "html", "json", "csv", "github-summary", "junit", "chat-message", "prometheus")
ANALYSIS_REPORTERS = ("text", "markdown", "html", "json", "csv", "github-summary", "chat-message", "prometheus")


@pytest.fixture
def diff_result(tmp_path: Path) -> DiffResult:
    before, after = hostile_pair(tmp_path)
    return logfold.diff(str(before), str(after), format="app", engine="native")


@pytest.fixture
def analysis_result(tmp_path: Path) -> AnalysisResult:
    _, after = hostile_pair(tmp_path)
    return logfold.analyze(str(after), format="app", engine="native")


def test_write_text_keeps_the_line_feed(tmp_path: Path) -> None:
    path = tmp_path / "out.txt"
    write_text(path, "one\ntwo\n")
    assert path.read_bytes() == b"one\ntwo\n"


def test_appended_text_keeps_the_line_feed(tmp_path: Path) -> None:
    path = tmp_path / "summary.md"
    write_text(path, "first")
    write_text(path, "second\nthird", append=True)
    assert path.read_bytes() == b"first\n\nsecond\nthird\n"


@pytest.mark.parametrize("reporter", ["prometheus", "markdown", "junit"])
def test_a_report_piped_from_the_command_line_has_no_carriage_return(tmp_path: Path, reporter: str) -> None:
    before, after = hostile_pair(tmp_path)
    completed = subprocess.run(
        [sys.executable, "-m", "logfold", "diff", str(before), str(after), "-f", "app", "--report", reporter, "-q"],
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout
    assert CARRIAGE_RETURN not in completed.stdout


@pytest.mark.parametrize("reporter", DIFF_REPORTERS)
def test_a_saved_diff_report_has_no_carriage_return(diff_result: DiffResult, tmp_path: Path, reporter: str) -> None:
    path = tmp_path / "report.out"
    diff_result.save(path, reporter)
    assert CARRIAGE_RETURN not in path.read_bytes()


@pytest.mark.parametrize("reporter", ANALYSIS_REPORTERS)
def test_a_saved_analysis_report_has_no_carriage_return(
    analysis_result: AnalysisResult, tmp_path: Path, reporter: str
) -> None:
    path = tmp_path / "report.out"
    analysis_result.save(path, reporter)
    assert CARRIAGE_RETURN not in path.read_bytes()
