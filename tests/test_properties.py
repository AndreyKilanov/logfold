"""Property-based tests: engine equivalence, count conservation and chunk-boundary invariance."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from logfold.ext.formats import PlainFormat, RegexFormat

pytestmark = requires_native

TOKENS = ["a", "b", "c", "err", "ok", "x1", "42", "10.0.0.1", "/tmp/x/y", "0xFF", "<*>", "é", "日本", "id=7", "-"]
SEPARATORS = [" ", " ", " ", "  ", "\t"]

token_lines = st.lists(
    st.tuples(st.lists(st.sampled_from(TOKENS), max_size=8), st.sampled_from(SEPARATORS)).map(
        lambda pair: pair[1].join(pair[0])
    ),
    min_size=1,
    max_size=60,
)
configs = st.fixed_dictionaries(
    {
        "depth": st.integers(3, 6),
        "sim_th": st.sampled_from([0.0, 0.3, 0.5, 0.8, 1.0]),
        "max_children": st.integers(1, 5),
        "max_templates": st.integers(1, 30),
    }
)
SETTINGS = settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.too_slow])


def snapshot(result: logfold.AnalysisResult) -> tuple[object, ...]:
    run = result.run
    return (
        (run.lines, run.records, run.unparsed, run.overflowed),
        [(t.id, t.text, t.count, t.example, dict(t.levels)) for t in result.templates],
    )


def write_lines(directory: str, lines: list[str], name: str = "x.log", eol: str = "\n") -> str:
    path = Path(directory) / name
    path.write_bytes((eol.join(lines) + eol).encode("utf-8"))
    return str(path)


@SETTINGS
@given(lines=token_lines, options=configs, eol=st.sampled_from(["\n", "\r\n"]))
def test_engines_agree_on_random_plain_logs(lines: list[str], options: dict[str, object], eol: str) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, lines, eol=eol)
        native_result = logfold.analyze(path, format="plain", engine="native", strategy="sequential", **options)  # type: ignore[arg-type]
        python_result = logfold.analyze(path, format="plain", engine="python", **options)  # type: ignore[arg-type]
    assert snapshot(native_result) == snapshot(python_result)
    assert sum(t.count for t in native_result.templates) == native_result.run.records
    ids = [t.id for t in native_result.templates]
    assert len(ids) == len(set(ids))


@SETTINGS
@given(lines=token_lines, options=configs)
def test_run_order_does_not_lose_records(lines: list[str], options: dict[str, object]) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, lines)
        result = logfold.diff(path, path, format="plain", **options)  # type: ignore[arg-type]
    assert result.before.records == result.after.records
    assert result.new_templates == ()
    assert result.disappeared == ()


RECORD_START = r"^\d{4} "
body_lines = st.lists(
    st.one_of(
        st.tuples(st.integers(1000, 9999), st.lists(st.sampled_from(TOKENS), max_size=6)).map(
            lambda pair: f"{pair[0]} " + " ".join(pair[1])
        ),
        st.lists(st.sampled_from(TOKENS), max_size=6).map(lambda tokens: "  " + " ".join(tokens)),
        st.just(""),
    ),
    min_size=1,
    max_size=80,
)


@SETTINGS
@given(lines=body_lines, chunk=st.integers(8, 400), threads=st.integers(1, 4), eol=st.sampled_from(["\n", "\r\n"]))
def test_chunk_boundaries_never_lose_or_duplicate_records(lines: list[str], chunk: int, threads: int, eol: str) -> None:
    spec = PlainFormat(record_start=RECORD_START, multiline=True)
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, lines, eol=eol)
        sequential = logfold.analyze(path, format=spec, engine="native", strategy="sequential")
        chunked = logfold.analyze(
            path, format=spec, engine="native", strategy="chunked", chunk_bytes=chunk, threads=threads
        )
    for field in ("lines", "records", "unparsed"):
        assert getattr(chunked.run, field) == getattr(sequential.run, field), field
    assert sum(t.count for t in chunked.templates) == chunked.run.records


@SETTINGS
@given(
    lines=st.lists(
        st.tuples(st.integers(0, 99), st.sampled_from(TOKENS)).map(lambda pair: f"line{pair[0]} {pair[1]}"),
        min_size=1,
        max_size=200,
    ),
    chunk=st.integers(16, 300),
)
def test_single_line_chunking_conserves_counters(lines: list[str], chunk: int) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, lines)
        sequential = logfold.analyze(path, format="plain", engine="native", strategy="sequential")
        chunked = logfold.analyze(
            path, format="plain", engine="native", strategy="chunked", chunk_bytes=chunk, threads=3
        )
    assert (chunked.run.lines, chunked.run.records) == (sequential.run.lines, sequential.run.records)


TIMESTAMPS = [
    "2026-10-04T12:00:00Z",
    "2026-10-04 12:00:00",
    "2026-10-04 12:00:00.123456789",
    "2026-10-04T12:00:00+05:30",
    "2026-10-04T12:00:00-0800",
    "2026-02-29T00:00:00Z",
    "2024-02-29T23:59:59,5Z",
    "2026-13-01T00:00:00Z",
    "2026-10-04",
    "2026-10-04T25:00:00Z",
    "2026-10-04T12:00:60Z",
    "1790000000",
    "1790000000123",
    "1790000000123456",
    "17900000001234567",
    "garbage",
    "",
    " 2026-10-04T12:00:00Z ",
    "2026-10-04T12:00:00+0530x",
]


def test_timestamp_parsing_agrees_for_json_strings_and_numbers() -> None:
    rows = [{"ts": value, "msg": f"row{index} marker"} for index, value in enumerate(TIMESTAMPS)]
    rows += [{"ts": 1790000000, "msg": "int-seconds marker"}, {"ts": 1790000000.5, "msg": "float marker"}]
    rows += [{"ts": 1.79e15, "msg": "float-micros marker"}, {"ts": True, "msg": "bool marker"}]
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, [json.dumps(r) for r in rows])
        kwargs = {"format": "jsonl", "sim_th": 1.0, "masks": []}
        native_result = logfold.analyze(path, engine="native", strategy="sequential", **kwargs)  # type: ignore[arg-type]
        python_result = logfold.analyze(path, engine="python", **kwargs)  # type: ignore[arg-type]
    assert snapshot(native_result) == snapshot(python_result)
    assert [(t.text, t.first_seen) for t in native_result.templates] == [
        (t.text, t.first_seen) for t in python_result.templates
    ]


STRPTIME_CASES = [
    (
        "%d/%b/%Y:%H:%M:%S %z",
        ["04/Oct/2026:12:00:00 +0300", "04/oct/2026:12:00:00 -0100", "31/Feb/2026:00:00:00 +0000"],
    ),
    ("%b %e %H:%M:%S", ["Oct  4 12:00:00", "Oct 14 12:00:00", "Foo  4 12:00:00", "Oct  4 12:00"]),
    ("%Y/%m/%d %H:%M:%S", ["2026/10/04 12:00:00", "2026/1/4 1:2:3", "2026/10/04"]),
    ("%y%m%d %T", ["261004 12:00:00", "991231 23:59:59", "690101 00:00:00"]),
    ("%Y-%j", ["2026-277", "2024-366", "2026-366", "2026-0"]),
    ("%B %d, %Y %H:%M:%S.%f", ["October 04, 2026 12:00:00.5", "October 04, 2026 12:00:00.123456789"]),
    ("%Y%m%dT%H%M%S%z", ["20261004T120000Z", "20261004T120000+0100"]),
]


@pytest.mark.parametrize(("ts_format", "samples"), STRPTIME_CASES)
def test_strptime_directives_agree(ts_format: str, samples: list[str]) -> None:
    spec = RegexFormat(
        pattern=r"^(?P<ts>[^|]*)\|(?P<msg>.*)$", message_group="msg", time_group="ts", ts_format=ts_format
    )
    lines = [f"{sample}|case{index} here" for index, sample in enumerate(samples)]
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, lines)
        kwargs = {"format": spec, "sim_th": 1.0, "masks": []}
        native_result = logfold.analyze(path, engine="native", strategy="sequential", **kwargs)  # type: ignore[arg-type]
        python_result = logfold.analyze(path, engine="python", **kwargs)  # type: ignore[arg-type]
    assert [(t.text, t.first_seen, t.last_seen) for t in native_result.templates] == [
        (t.text, t.first_seen, t.last_seen) for t in python_result.templates
    ]
    assert native_result.run.tz_aware == python_result.run.tz_aware
