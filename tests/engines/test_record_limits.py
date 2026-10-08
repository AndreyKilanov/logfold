"""A line and a multi-line record have a fixed size limit, the same in every strategy (ALGORITHM.md 1.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold.ext.formats import PlainFormat

MAX_LINE_BYTES = 16 << 20
MAX_RECORD_BYTES = 1 << 20
CR = b"\r"
LF = b"\n"
MULTILINE = PlainFormat(record_start=r"^\d{4}-", multiline=True)

Summary = tuple[list[tuple[str, int]], int, int, int]


def run(path: Path, **options: object) -> Summary:
    result = logfold.analyze(str(path), examples="none", **options)  # type: ignore[arg-type]
    templates = sorted((t.text, t.count) for t in result.templates)
    return templates, result.run.records, result.run.lines, result.run.unparsed


def write(path: Path, *parts: bytes) -> Path:
    path.write_bytes(b"".join(parts))
    return path


def longest(summary: Summary) -> int:
    return max(len(text) for text, _ in summary[0])


@pytest.mark.parametrize("raw", [MAX_LINE_BYTES - 1, MAX_LINE_BYTES, MAX_LINE_BYTES + 1, MAX_LINE_BYTES + 2])
@pytest.mark.parametrize("ends_in_cr", [False, True])
def test_a_long_line_keeps_its_first_bytes(tmp_path: Path, raw: int, ends_in_cr: bool) -> None:
    body = bytearray(b"y" * raw)
    if ends_in_cr:
        body[-1:] = CR
    path = write(tmp_path / "long.log", b"first line", LF, bytes(body), LF, b"last line", LF)
    expected = run(path, format="plain", engine="native")
    assert expected[2] == 3
    assert longest(expected) == min(raw - ends_in_cr, MAX_LINE_BYTES)


@requires_native
@pytest.mark.parametrize("raw", [MAX_LINE_BYTES - 1, MAX_LINE_BYTES, MAX_LINE_BYTES + 1, MAX_LINE_BYTES + 2])
@pytest.mark.parametrize("ends_in_cr", [False, True])
def test_every_strategy_cuts_a_long_line_at_the_same_place(tmp_path: Path, raw: int, ends_in_cr: bool) -> None:
    body = bytearray(b"y" * raw)
    if ends_in_cr:
        body[-1:] = CR
    path = write(tmp_path / "long.log", b"first line", LF, bytes(body), LF, b"last line", LF)
    expected = run(path, format="plain", engine="native")
    assert run(path, format="plain", engine="native", strategy="sequential") == expected
    assert run(path, format="plain", engine="native", strategy="chunked", chunk_bytes=1 << 20) == expected


@requires_native
def test_chunks_that_start_inside_a_very_long_line_agree_with_one_pass(tmp_path: Path) -> None:
    path = write(
        tmp_path / "huge.log",
        b"before",
        LF,
        b"w" * (3 * MAX_LINE_BYTES + 11),
        LF,
        b"after one",
        LF,
        b"v" * (MAX_LINE_BYTES + 3),
        LF,
        b"after two",
        LF,
    )
    expected = run(path, format="plain", engine="native")
    assert expected[2] == 5
    assert run(path, format="plain", engine="native", strategy="sequential") == expected
    for chunk in (1 << 20, 5 << 20, 17 << 20):
        assert run(path, format="plain", engine="native", strategy="chunked", chunk_bytes=chunk) == expected


def record_log(path: Path, lines: int) -> Path:
    body = b"  " + b"x" * 97 + LF
    return write(path, b"2026-01-01 first", LF, body * lines, b"2026-01-02 second", LF, b"2026-01-03 third", LF)


@requires_native
@pytest.mark.parametrize(
    "lines", [10, MAX_RECORD_BYTES // 100 - 1, MAX_RECORD_BYTES // 100 + 1, 3 * MAX_RECORD_BYTES // 100]
)
def test_a_record_takes_lines_up_to_the_limit_in_every_strategy(tmp_path: Path, lines: int) -> None:
    path = record_log(tmp_path / "record.log", lines)
    expected = run(path, format=MULTILINE, engine="native")
    assert expected[2] == lines + 3
    assert run(path, format=MULTILINE, engine="native", strategy="sequential") == expected
    assert run(path, format=MULTILINE, engine="native", strategy="chunked", chunk_bytes=1 << 20) == expected


def test_a_huge_record_is_cut_and_its_lines_are_still_counted(tmp_path: Path) -> None:
    lines = 5 * MAX_RECORD_BYTES // 100
    path = record_log(tmp_path / "record.log", lines)
    summary = run(path, format=MULTILINE, engine="native")
    assert summary[2] == lines + 3
    assert summary[1] == 3
    assert MAX_RECORD_BYTES * 9 // 10 <= longest(summary) < MAX_RECORD_BYTES + 200  # a template drops the line breaks
