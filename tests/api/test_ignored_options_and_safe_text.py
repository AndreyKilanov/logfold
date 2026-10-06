from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

import logfold
from logfold.config import DEFAULT_CHUNK_BYTES
from logfold.ext import printable

ESCAPE_LINE = "2026-10-04T00:00:00Z ERROR \x1b]0;pwned\x07 disk \x9b31m failure on /dev/sda3\n"


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
    result = logfold.analyze(small_log, format="app", warm_start=True, chunk_bytes=4 << 20, engine="python")
    assert [w.split(" was ignored")[0] for w in ignored(result)] == ["warm_start", "chunk_bytes"]


def test_the_reason_names_the_cause(small_log: str) -> None:
    python = logfold.analyze(small_log, format="app", warm_start=True, engine="python")
    assert "the python engine is always sequential" in ignored(python)[0]
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
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "hostile.log"
        path.write_text(ESCAPE_LINE * 5, encoding="utf-8")
        result = logfold.analyze(str(path), format="app")
    run = dataclasses.replace(result.run, name="runs\x1b[31m.log")
    return dataclasses.replace(result, run=run, warnings=("bad \x1b[2J warning",))


@pytest.mark.parametrize("reporter", ["text", "markdown"])
def test_text_reporters_do_not_pass_control_characters(hostile: logfold.AnalysisResult, reporter: str) -> None:
    text = hostile.render(reporter)
    assert not [char for char in text if ord(char) < 0x20 and char not in "\n\t"]
    assert not [char for char in text if 0x7F <= ord(char) <= 0x9F]
    assert "\\x1b" in text
    assert "\\x07" in text


def test_markdown_still_neutralizes_cells(tmp_path: Path) -> None:
    path = tmp_path / "pipes.log"
    path.write_text("2026-10-04T00:00:00Z ERROR a | b `c` d\n" * 3, encoding="utf-8")
    text = logfold.analyze(str(path), format="app").render("markdown")
    assert "a / b 'c' d" in text


def test_csv_keeps_the_raw_values(hostile: logfold.AnalysisResult) -> None:
    assert "\x1b" in hostile.render("csv")


def test_json_escapes_control_characters_itself(hostile: logfold.AnalysisResult) -> None:
    assert "\x1b" not in hostile.render("json")


def test_printable_keeps_tabs_and_newlines_and_is_idempotent() -> None:
    assert printable("a\tb\nc") == "a\tb\nc"
    assert printable("\x00\x08\x0d\x1b\x7f\x80\x9f") == "\\x00\\x08\\x0d\\x1b\\x7f\\x80\\x9f"
    once = printable("x\x1b[0m")
    assert printable(once) == once
    assert printable("плоский текст ✓") == "плоский текст ✓"
