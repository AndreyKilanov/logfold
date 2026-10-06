from __future__ import annotations

import gzip
import tracemalloc
from pathlib import Path

from logfold.api.inspecting import inspect_file
from logfold.cli.levels import _keeps
from logfold.formats.auto import MAX_SAMPLE_BYTES, MAX_SAMPLE_LINE_BYTES, read_sample

MIB = 1 << 20


def test_a_long_line_is_cut_and_the_next_lines_are_still_read(tmp_path: Path) -> None:
    path = tmp_path / "long.log"
    path.write_bytes(b"x" * (3 * MIB) + b"\nsecond\nthird\n")
    lines = read_sample(str(path))
    assert [len(lines[0]), *lines[1:]] == [MAX_SAMPLE_LINE_BYTES, "second", "third"]


def test_a_line_of_exactly_the_limit_is_kept_whole(tmp_path: Path) -> None:
    path = tmp_path / "exact.log"
    path.write_bytes(b"y" * MAX_SAMPLE_LINE_BYTES + b"\nnext\n")
    lines = read_sample(str(path))
    assert [len(lines[0]), lines[1]] == [MAX_SAMPLE_LINE_BYTES, "next"]


def test_the_whole_sample_has_a_byte_budget(tmp_path: Path) -> None:
    path = tmp_path / "wide.log"
    path.write_bytes((b"z" * (MIB - 1) + b"\n") * 40)
    lines = read_sample(str(path), 1000)
    assert 0 < len(lines) <= MAX_SAMPLE_BYTES // MIB


def test_memory_stays_small_for_a_file_that_is_one_huge_line(tmp_path: Path) -> None:
    path = tmp_path / "oneline.log"
    with path.open("wb") as handle:
        for _ in range(40):
            handle.write(b"q" * MIB)
    tracemalloc.start()
    try:
        found = inspect_file(path, format="plain")
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert found.records == 1
    assert len(found.shown[0].message) == MAX_SAMPLE_LINE_BYTES
    assert peak < 32 * MIB


def test_a_gzip_bomb_line_is_bounded_too(tmp_path: Path) -> None:
    path = tmp_path / "bomb.log.gz"
    with gzip.open(path, "wb") as handle:
        for _ in range(64):
            handle.write(b"w" * MIB)
    tracemalloc.start()
    try:
        lines = read_sample(str(path))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert len(lines) == 1
    assert peak < 32 * MIB


def test_an_unknown_level_name_is_not_kept_by_the_filter() -> None:
    assert _keeps("ERROR", "WARN") is True
    assert _keeps("INFO", "WARN") is False
    assert _keeps("BANANA", "TRACE") is False
    assert _keeps(None, "TRACE") is False
