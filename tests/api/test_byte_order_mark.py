"""A UTF-8 byte order mark at the start of a log changes nothing: the first line is read like the others.

For every built-in format and the plugin formats that have a grammar (``tests/format_grammars.py``) the same log is read
with and without the mark, in one run and in small chunks; the lines, records, lines not parsed, records per level and
templates must be the same. The sample of ``--format auto`` and of ``inspect`` drops the mark too.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from format_grammars import GRAMMARS
from logfold.formats.auto import read_sample

pytestmark = requires_native

BOM = b"\xef\xbb\xbf"
LINE_FEED = chr(10).encode()
SETTINGS = settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def shape(result: logfold.AnalysisResult) -> tuple[object, ...]:
    run = result.run
    templates = sorted((t.text, t.count) for t in result.templates)
    return run.lines, run.records, run.unparsed, dict(result.levels), templates


@pytest.mark.parametrize("name", sorted(GRAMMARS))
def test_the_mark_changes_nothing_for_any_format(name: str) -> None:
    @SETTINGS
    @given(lines=st.lists(GRAMMARS[name], min_size=1, max_size=20), chunk=st.sampled_from([17, 64]))
    def check(lines: list[str], chunk: int) -> None:
        data = LINE_FEED.join(line.encode() for line in lines) + LINE_FEED
        with tempfile.TemporaryDirectory() as folder:
            plain, marked = Path(folder) / "plain.log", Path(folder) / "marked.log"
            plain.write_bytes(data)
            marked.write_bytes(BOM + data)
            for options in ({"strategy": "sequential"}, {"strategy": "chunked", "chunk_bytes": chunk, "threads": 2}):
                assert shape(logfold.analyze(marked, format=name, **options)) == shape(
                    logfold.analyze(plain, format=name, **options)
                )

    check()


def test_the_first_line_of_the_sample_has_no_mark(tmp_path: Path) -> None:
    log = tmp_path / "marked.log"
    log.write_bytes(
        BOM + b"2026-10-04 12:00:00,123 INFO [main] hello" + LINE_FEED + b"2026-10-04 12:00:01,123 INFO [main] bye"
    )
    assert read_sample(str(log))[0].startswith("2026")
    assert logfold.analyze(log, format="auto").meta.format == "app"


def test_a_mark_in_the_middle_of_a_file_is_kept(tmp_path: Path) -> None:
    log = tmp_path / "middle.log"
    log.write_bytes(b"first" + LINE_FEED + BOM + b"second" + LINE_FEED)
    seen = logfold.inspect_file(log, format="plain", sample_lines=10, limit=10)
    assert [record.message for record in seen.shown] == ["first", "﻿second"]
