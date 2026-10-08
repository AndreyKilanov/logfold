"""Property-based tests: count conservation and chunk-boundary invariance."""

from __future__ import annotations

import tempfile
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from logfold.ext.formats import PlainFormat

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


def write_lines(directory: str, lines: list[str], name: str = "x.log", eol: str = "\n") -> str:
    path = Path(directory) / name
    path.write_bytes((eol.join(lines) + eol).encode("utf-8"))
    return str(path)


@SETTINGS
@given(lines=token_lines, options=configs, eol=st.sampled_from(["\n", "\r\n"]))
def test_random_plain_logs_conserve_counts_and_have_unique_ids(
    lines: list[str], options: dict[str, object], eol: str
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = write_lines(directory, lines, eol=eol)
        native_result = logfold.analyze(path, format="plain", engine="native", strategy="sequential", **options)  # type: ignore[arg-type]
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
