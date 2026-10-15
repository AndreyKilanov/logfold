"""Fuzz the built-in formats: damaged logs never break them and the chunking never changes the result.

For every format a Hypothesis strategy writes lines of that format (``tests/format_grammars.py``) and damages the
log. The invariants:

* no error and no hang (a run that takes more than the deadline fails the example);
* conservation: every non-blank line is in one record or in the count of lines not parsed;
* the sample reader (``inspect``) and the run (``analyze``) agree on the records and the lines not parsed;
* the result does not depend on the chunking: records, lines, lines not parsed and records per level are the same
  for the sequential run and for runs in small chunks on 1 to 4 threads.

The default profile is quick. For a long run set ``LOGFOLD_FUZZ_EXAMPLES`` (``20000`` takes some hours for all formats).
"""

from __future__ import annotations

import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from format_grammars import GRAMMARS, mutated_log

pytestmark = requires_native

EXAMPLES = int(os.environ.get("LOGFOLD_FUZZ_EXAMPLES", "40"))
SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=timedelta(seconds=30),
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
LOG4J_PATTERNS = ["log4j", "log4j:%d{ISO8601} %-5p [%t] %c - %m%n", "log4j:[%d] %p %m (%c)%n"]
BLANK = b" \t\n\x0c\r"
UTF8_BOM = bytes([0xEF, 0xBB, 0xBF])
HUGE = 10_000_000
SMALL_LOG = 3000
MAX_UNITS = 60
JOINING = {"docker-json"}
"""Formats that join entries into one record: the lines of one inspected record are not counted per record."""


def write(data: bytes) -> tuple[tempfile.TemporaryDirectory[str], Path]:
    directory = tempfile.TemporaryDirectory()
    path = Path(directory.name) / "fuzz.log"
    path.write_bytes(data)
    return directory, path


def chunk_for(data: bytes, chunk: int) -> int:
    """Return the chunk size to use: tiny chunks only for small logs (1 byte chunks of a long log are 100,000 units)."""
    return chunk if len(data) <= SMALL_LOG else max(chunk, len(data) // MAX_UNITS)


def non_blank_lines(data: bytes) -> int:
    """Count the lines that the engine counts: split on a line feed, a line of ASCII white space only is blank.

    A UTF-8 byte order mark at the start of the log is not part of its first line.
    """
    return sum(1 for line in data.removeprefix(UTF8_BOM).split(b"\n") if line.strip(BLANK))


def summary(result: logfold.AnalysisResult) -> tuple[int, int, int, dict[str, int]]:
    run = result.run
    return run.lines, run.records, run.unparsed, dict(result.levels)


@pytest.mark.parametrize("name", sorted(GRAMMARS))
def test_every_line_is_in_a_record_or_unparsed(name: str) -> None:
    @SETTINGS
    @given(data=mutated_log(GRAMMARS[name]))
    def check(data: bytes) -> None:
        directory, path = write(data)
        with directory:
            seen = logfold.inspect_file(path, format=name, sample_lines=HUGE, limit=HUGE)
            assert seen.lines == non_blank_lines(data)
            if name not in JOINING:
                assert sum(record.lines for record in seen.shown) + seen.unparsed == seen.lines
            assert seen.records == len(seen.shown)

    check()


@pytest.mark.parametrize("name", sorted(GRAMMARS))
def test_the_result_does_not_depend_on_the_chunking(name: str) -> None:
    @SETTINGS
    @given(
        data=mutated_log(GRAMMARS[name]),
        chunk=st.sampled_from([1, 3, 17, 64, 250]),
        threads=st.integers(1, 4),
    )
    def check(data: bytes, chunk: int, threads: int) -> None:
        directory, path = write(data)
        with directory:
            whole = logfold.analyze(path, format=name, strategy="sequential")
            parts = logfold.analyze(
                path, format=name, strategy="chunked", chunk_bytes=chunk_for(data, chunk), threads=threads
            )
            assert summary(parts) == summary(whole)
            assert sum(t.count for t in parts.templates) == parts.run.records
            seen = logfold.inspect_file(path, format=name, sample_lines=HUGE, limit=0)
            assert (seen.records, seen.unparsed) == (whole.run.records, whole.run.unparsed)

    check()


@pytest.mark.parametrize("pattern", LOG4J_PATTERNS[1:])
def test_log4j_patterns_hold_the_same_invariants(pattern: str) -> None:
    @SETTINGS
    @given(data=mutated_log(GRAMMARS["log4j"]), chunk=st.sampled_from([1, 17, 250]), threads=st.integers(1, 3))
    def check(data: bytes, chunk: int, threads: int) -> None:
        directory, path = write(data)
        with directory:
            seen = logfold.inspect_file(path, format=pattern, sample_lines=HUGE, limit=HUGE)
            assert seen.lines == non_blank_lines(data)
            assert sum(record.lines for record in seen.shown) + seen.unparsed == seen.lines
            whole = logfold.analyze(path, format=pattern, strategy="sequential")
            parts = logfold.analyze(
                path, format=pattern, strategy="chunked", chunk_bytes=chunk_for(data, chunk), threads=threads
            )
            assert summary(parts) == summary(whole)

    check()
