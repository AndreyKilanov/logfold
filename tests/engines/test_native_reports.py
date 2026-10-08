"""The native pipeline reports give exactly the text of the pure-Python reference reporters."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from corpora import hostile_pair
from logfold.ext import get_reporter, native_reports
from logfold.model import AnalysisResult, DiffEntry, DiffResult, RunSummary, Template
from logfold.plugins import report_data

pytestmark = requires_native


@pytest.fixture(autouse=True)
def always_native(monkeypatch: pytest.MonkeyPatch) -> None:
    """Route every call to the extension, so that these tests compare the two implementations on small results."""
    monkeypatch.setattr(report_data, "MIN_LISTED", 0)
    monkeypatch.setattr(report_data, "LISTED_FRACTION", 10**9)


PIECES = st.sampled_from(
    [
        "a", "word", "<NUM>", "<*>", "x" * 90, "y" * 450, "`", "``", "|", '"', chr(92), "&", "<", ">", "]]>",
        "<!here>", "<@U123>", "<#C1>", "@channel", "@HERE", "@all", "@everyone", "@channels", "@all_", "@all.", "@ALL",
        "\x1b[31m", "\x00", "\x07", "\x1f", "\x7f", "\x85", "\t", "\n", "\r", " ", "  ", chr(0xA0), chr(0x2028),
        chr(0x3000), chr(0x200B), chr(0xFFFE), chr(0xFFFF), chr(0x301), "é", "Ж", "日本語", "\U0001f642", "\U00010000",
    ]
)  # fmt: skip
TEXTS = st.lists(PIECES, max_size=9)
TEXT = st.one_of(TEXTS.map(" ".join), TEXTS.map("".join))
NAME = st.one_of(
    TEXT, st.just("C:" + chr(92) + "logs" + chr(92) + "app.log"), st.just("/var/" + "d" * 200 + "/app.log")
)
LEVEL = st.sampled_from([None, None, "TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "ERRORISH", "<b>x</b>"])
COUNT = st.integers(0, 2**53)
RATIO = st.one_of(st.none(), st.floats(0.0, 1e9, allow_nan=False), st.just(2.0))
MOMENT = st.one_of(
    st.none(),
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)),
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1), timezones=st.just(UTC)),
)
SETTINGS = settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@cache
def bases() -> tuple[AnalysisResult, DiffResult]:
    import tempfile

    with tempfile.TemporaryDirectory() as folder:
        before, after = hostile_pair(Path(folder))
        diff = logfold.diff(str(before), str(after), format="app", engine="python")
        analysis = logfold.analyze(str(after), format="app", engine="python")
    return analysis, diff


@st.composite
def entries(draw: st.DrawFn) -> DiffEntry:
    text = draw(TEXT)
    level = draw(LEVEL)
    return DiffEntry(
        id=draw(st.sampled_from(["0123456789abcdef", "ffffffffffffffff", "ab" + chr(92) + '"c', ""])),
        text=text,
        before_count=draw(COUNT),
        after_count=draw(COUNT),
        before_share=0.0,
        after_share=0.0,
        ratio=draw(RATIO),
        level=level,
        levels={},
        example=None,
        first_seen=draw(MOMENT),
        last_seen=draw(MOMENT),
    )


@st.composite
def templates(draw: st.DrawFn) -> Template:
    return Template(
        id=draw(st.sampled_from(["0123456789abcdef", "ffffffffffffffff", "ab" + chr(92) + '"c', ""])),
        text=draw(TEXT),
        count=draw(COUNT),
        first_seen=None,
        last_seen=None,
        example=None,
        level=draw(LEVEL),
        levels={},
    )


def run(name: str, records: int, unparsed: int) -> RunSummary:
    return RunSummary(name, 1, records + unparsed, records, unparsed, 0, False, False)


@st.composite
def diffs(draw: st.DrawFn) -> DiffResult:
    _, base = bases()
    lists = [tuple(draw(st.lists(entries(), max_size=6))) for _ in range(3)]
    return replace(
        base,
        new_templates=lists[0],
        changed=lists[1],
        disappeared=lists[2],
        unchanged=draw(COUNT),
        before=run(draw(NAME), draw(st.sampled_from([0, 1, 7, 1234567])), 0),
        after=run(draw(NAME), draw(st.sampled_from([0, 1, 7, 1234567, 10**12])), 0),
        warnings=tuple(draw(st.lists(TEXT, max_size=2))),
    )


@st.composite
def analyses(draw: st.DrawFn) -> AnalysisResult:
    base, _ = bases()
    items = tuple(sorted(draw(st.lists(templates(), max_size=7)), key=lambda t: -t.count))
    return replace(
        base,
        templates=items,
        run=run(draw(NAME), draw(st.sampled_from([0, 1, 7, 1234567, 10**12])), draw(st.sampled_from([0, 3, 10**6]))),
        warnings=tuple(draw(st.lists(TEXT, max_size=2))),
    )


OPTIONS = st.fixed_dictionaries(
    {},
    optional={
        "top": st.one_of(st.integers(0, 8), st.sampled_from([20, 100, 10**6, 10**30])),
        "max_bytes": st.one_of(st.integers(0, 4000), st.just(10**6)),
        "max_chars": st.one_of(st.integers(0, 900), st.just(3000)),
    },
)


LIMITS = {"github-summary": "max_bytes", "chat-message": "max_chars"}


def same(name: str, result: AnalysisResult | DiffResult, options: dict[str, int]) -> None:
    reporter = get_reporter(name)
    assert native_reports.get_renderer() is not None
    keep = {"top", LIMITS.get(name, "top")}
    options = {key: value for key, value in options.items() if key in keep}
    assert reporter.render(result, **options) == reporter.render_reference(result, **options)  # type: ignore[attr-defined]


@pytest.mark.parametrize("name", ["github-summary", "junit", "chat-message", "prometheus"])
@SETTINGS
@given(result=diffs(), options=OPTIONS)
def test_native_diff_reports_equal_the_reference(name: str, result: DiffResult, options: dict[str, int]) -> None:
    same(name, result, options)


@pytest.mark.parametrize("name", ["github-summary", "chat-message", "prometheus"])
@SETTINGS
@given(result=analyses(), options=OPTIONS)
def test_native_analysis_reports_equal_the_reference(
    name: str, result: AnalysisResult, options: dict[str, int]
) -> None:
    same(name, result, options)


@pytest.mark.parametrize("name", ["github-summary", "junit", "chat-message", "prometheus"])
def test_native_reports_equal_the_reference_on_real_results(name: str, corpus_dir: Path) -> None:
    diff = logfold.diff(str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app")
    analysis = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    for result in (diff, analysis):
        kind = "diff" if isinstance(result, DiffResult) else "analysis"
        if kind in get_reporter(name).kinds:
            for options in ({}, {"top": 3}, {"top": 100000}):
                same(name, result, options)


def test_the_native_text_is_what_the_default_reporters_write(tmp_path: Path) -> None:
    before, after = hostile_pair(tmp_path)
    result = logfold.diff(str(before), str(after), format="app")
    assert result.render("junit") == get_reporter("junit").render_reference(result)  # type: ignore[attr-defined]


def test_a_lone_surrogate_falls_back_to_the_reference() -> None:
    _, base = bases()
    entry = replace(base.new_templates[0], text="bad " + chr(0xD800) + " text")
    result = replace(base, new_templates=(entry,))
    assert "bad" in get_reporter("chat-message").render(result)


def test_the_size_limits_cut_at_the_same_place_at_every_boundary(tmp_path: Path) -> None:
    before, after = hostile_pair(tmp_path)
    diff = logfold.diff(str(before), str(after), format="app", engine="python")
    analysis = logfold.analyze(str(after), format="app", engine="python")
    for limit in range(0, 1400, 3):
        same("chat-message", diff, {"top": 50, "max_chars": limit})
        same("chat-message", analysis, {"top": 50, "max_chars": limit})
    for limit in range(0, 3200, 7):
        same("github-summary", diff, {"top": 50, "max_bytes": limit})
        same("github-summary", analysis, {"top": 50, "max_bytes": limit})


@pytest.fixture
def native_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    real = native_reports.get_renderer()
    assert real is not None

    def spy(name: str, data: dict[str, object], options: dict[str, object]) -> str:
        calls.append(name)
        return real(name, data, options)

    monkeypatch.setattr(native_reports, "get_renderer", lambda: spy)
    monkeypatch.setattr(report_data, "get_renderer", lambda: spy)
    return calls


def test_a_short_listing_is_rendered_in_python_and_a_long_one_in_rust(
    native_calls: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_data, "MIN_LISTED", 5)
    _, diff = bases()
    many = replace(diff, new_templates=diff.new_templates * 3)
    reporter = get_reporter("prometheus")
    reporter.render(many, top=1)
    assert native_calls == []
    reporter.render(many, top=50)
    assert native_calls == ["prometheus"]
    assert reporter.render(many, top=1) == reporter.render_reference(many, top=1)


def test_a_huge_top_does_not_render_the_document_again_and_again(tmp_path: Path) -> None:
    before, after = hostile_pair(tmp_path)
    diff = logfold.diff(str(before), str(after), format="app", engine="python")
    many = replace(diff, new_templates=diff.new_templates * 400)
    for top in (10**6, 10**30):
        same("github-summary", many, {"top": top, "max_bytes": 5000})
    text = get_reporter("github-summary").render(many, top=10**30, max_bytes=5000)
    assert "_Lists are shortened to " in text
    assert len(text.encode("utf-8")) <= 5000


@pytest.mark.parametrize("count", [-5, 2**70])
def test_counts_the_extension_cannot_take_are_rendered_in_python(count: int) -> None:
    _, base = bases()
    entry = replace(base.new_templates[0], after_count=count)
    result = replace(base, new_templates=(entry,))
    for name in ("github-summary", "junit", "chat-message", "prometheus"):
        reporter = get_reporter(name)
        assert reporter.render(result) == reporter.render_reference(result)  # type: ignore[attr-defined]
        assert f"{count:,}" in reporter.render(result) or str(count) in reporter.render(result)
