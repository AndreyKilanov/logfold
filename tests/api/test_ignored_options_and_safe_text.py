from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path

import pytest

import logfold
from logfold.config import DEFAULT_CHUNK_BYTES
from logfold.ext import printable

ESCAPE_LINE = "2026-10-04T00:00:00Z ERROR \x1b]0;pwned\x07 disk \x9b31m failure on /dev/sda3\n"
REPORTERS = ["text", "markdown", "csv", "json", "html"]


@pytest.fixture(scope="module")
def small_log(tmp_path_factory: pytest.TempPathFactory) -> str:
    path = tmp_path_factory.mktemp("small") / "small.log"
    path.write_text("2026-10-04T00:00:00Z INFO started\n" * 50, encoding="utf-8")
    return str(path)


def ignored(result: logfold.AnalysisResult | logfold.DiffResult) -> list[str]:
    return [warning for warning in result.warnings if "was ignored" in warning]


def test_warm_start_on_a_sequential_run_is_reported(small_log: str) -> None:
    result = logfold.analyze(small_log, format="app", warm_start=True)
    assert result.metrics.strategy == "sequential"
    (warning,) = ignored(result)
    assert warning.startswith("warm_start was ignored")
    assert "strategy='chunked'" in warning


def test_a_chunk_size_is_reported_when_something_forced_the_run_to_be_sequential(small_log: str) -> None:
    result = logfold.analyze(small_log, format="app", chunk_bytes=4 << 20, strategy="sequential")
    (warning,) = ignored(result)
    assert warning.startswith("chunk_bytes was ignored")


def test_a_chunk_size_with_auto_is_a_threshold_not_an_ignored_option(small_log: str) -> None:
    result = logfold.analyze(small_log, format="app", chunk_bytes=4 << 20)
    assert result.metrics.strategy == "sequential"
    assert ignored(result) == []


def test_both_are_reported_once_each(small_log: str) -> None:
    result = logfold.analyze(small_log, format="app", warm_start=True, chunk_bytes=4 << 20, strategy="sequential")
    assert [w.split(" was ignored")[0] for w in ignored(result)] == ["warm_start", "chunk_bytes"]


def test_the_reason_names_the_cause(small_log: str) -> None:
    sequential = logfold.analyze(small_log, format="app", warm_start=True, strategy="sequential")
    assert "strategy='sequential' was asked for" in ignored(sequential)[0]
    cardinality = logfold.analyze(small_log, format="app", warm_start=True, high_cardinality=True)
    assert "high_cardinality runs sequentially" in ignored(cardinality)[0]


def test_the_chunked_strategy_uses_the_options_so_there_is_no_warning(small_log: str) -> None:
    result = logfold.analyze(small_log, format="app", strategy="chunked", warm_start=True, chunk_bytes=4 << 20)
    assert result.metrics.strategy == "chunked"
    assert ignored(result) == []


def test_defaults_and_the_default_chunk_size_give_no_warning(small_log: str) -> None:
    assert ignored(logfold.analyze(small_log, format="app")) == []
    assert ignored(logfold.analyze(small_log, format="app", chunk_bytes=DEFAULT_CHUNK_BYTES)) == []


def test_diff_reports_it_too(small_log: str) -> None:
    result = logfold.diff(small_log, small_log, format="app", warm_start=True)
    (warning,) = ignored(result)
    assert warning.startswith("warm_start was ignored")


@pytest.fixture(scope="module")
def hostile() -> logfold.AnalysisResult:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "hostile.log"
        path.write_text(ESCAPE_LINE * 5, encoding="utf-8")
        result = logfold.analyze(str(path), format="app")
    run = dataclasses.replace(result.run, name="runs\x1b[31m.log")
    return dataclasses.replace(result, run=run, warnings=("bad \x1b[2J warning",))


def raw_control_characters(text: str) -> list[str]:
    return [char for char in text if (ord(char) < 0x20 and char not in "\n\t") or 0x7F <= ord(char) <= 0x9F]


@pytest.mark.parametrize("reporter", REPORTERS)
def test_no_reporter_returns_raw_control_characters(hostile: logfold.AnalysisResult, reporter: str) -> None:
    assert raw_control_characters(hostile.render(reporter)) == []


@pytest.mark.parametrize("reporter", REPORTERS)
def test_a_diff_is_safe_in_every_reporter(tmp_path: Path, reporter: str) -> None:
    before, after = tmp_path / "before.log", tmp_path / "after.log"
    before.write_text("2026-10-04T00:00:00Z INFO fine\n" * 5, encoding="utf-8")
    after.write_text(ESCAPE_LINE * 5, encoding="utf-8")
    comparison = logfold.diff(str(before), str(after), format="app")
    assert comparison.new_templates
    assert raw_control_characters(comparison.render(reporter)) == []


@pytest.mark.parametrize("reporter", ["text", "markdown", "csv"])
def test_the_escapes_are_visible_instead(hostile: logfold.AnalysisResult, reporter: str) -> None:
    assert "\\x1b" in hostile.render(reporter)


def test_html_shows_the_escapes_in_the_example(hostile: logfold.AnalysisResult) -> None:
    text = hostile.render("html")
    assert "\\x1b" in text
    assert "\\x07" in text


def test_json_keeps_the_data_and_only_escapes_the_encoding(hostile: logfold.AnalysisResult) -> None:
    text = hostile.render("json")
    assert "\\u009b" in text
    assert "\\u001b" in text
    example = json.loads(text)["templates"][0]["example"]
    assert "\x1b" in example
    assert "\x9b" in example


def test_the_json_report_still_loads_back(hostile: logfold.AnalysisResult, tmp_path: Path) -> None:
    target = tmp_path / "hostile.json"
    hostile.to_json(target)
    assert logfold.load_analysis(target).templates == hostile.templates


def test_the_result_attributes_stay_raw_because_they_are_data(hostile: logfold.AnalysisResult) -> None:
    assert "\x1b" in (hostile.templates[0].example or "")


def test_markdown_still_neutralizes_cells(tmp_path: Path) -> None:
    path = tmp_path / "pipes.log"
    path.write_text("2026-10-04T00:00:00Z ERROR a | b `c` d\n" * 3, encoding="utf-8")
    text = logfold.analyze(str(path), format="app").render("markdown")
    assert "a / b 'c' d" in text


def test_csv_still_guards_formulas(tmp_path: Path) -> None:
    path = tmp_path / "formula.log"
    path.write_text("2026-10-04T00:00:00Z ERROR =HYPERLINK(x)\n" * 3, encoding="utf-8")
    text = logfold.analyze(str(path), format="app").render("csv")
    assert "'=HYPERLINK" in text


def test_printable_keeps_tabs_and_newlines_and_is_idempotent() -> None:
    assert printable("a\tb\nc") == "a\tb\nc"
    assert printable("\x00\x08\x0d\x1b\x7f\x80\x9f") == "\\x00\\x08\\x0d\\x1b\\x7f\\x80\\x9f"
    once = printable("x\x1b[0m")
    assert printable(once) == once
    assert printable("плоский текст ✓") == "плоский текст ✓"
