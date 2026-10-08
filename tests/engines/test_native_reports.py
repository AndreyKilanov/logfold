"""The pipeline reports render any result, and refuse a result they cannot show with a clear error."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from xml.etree import ElementTree

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from corpora import hostile_pair
from logfold.errors import ConfigError
from logfold.ext import get_reporter
from logfold.model import AnalysisResult, DiffEntry, DiffResult, RunSummary, Template

pytestmark = requires_native


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
        diff = logfold.diff(str(before), str(after), format="app", engine="native")
        analysis = logfold.analyze(str(after), format="app", engine="native")
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


REPORTS = ["github-summary", "junit", "chat-message", "prometheus"]


def render(name: str, result: AnalysisResult | DiffResult, options: dict[str, int]) -> str:
    keep = {"top", {"github-summary": "max_bytes", "chat-message": "max_chars"}.get(name, "top")}
    return get_reporter(name).render(result, **{key: value for key, value in options.items() if key in keep})


@pytest.mark.parametrize("name", REPORTS)
@SETTINGS
@given(result=diffs(), options=OPTIONS)
def test_a_diff_of_any_text_renders(name: str, result: DiffResult, options: dict[str, int]) -> None:
    text = render(name, result, options)
    assert text.endswith("\n")
    if name == "junit":
        ElementTree.fromstring(text)


@pytest.mark.parametrize("name", ["github-summary", "chat-message", "prometheus"])
@SETTINGS
@given(result=analyses(), options=OPTIONS)
def test_an_analysis_of_any_text_renders(name: str, result: AnalysisResult, options: dict[str, int]) -> None:
    assert render(name, result, options).endswith("\n")


@pytest.mark.parametrize("name", REPORTS)
def test_real_results_render_with_every_size_of_listing(name: str, corpus_dir: Path) -> None:
    diff = logfold.diff(str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app")
    analysis = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    for result in (diff, analysis):
        kind = "diff" if isinstance(result, DiffResult) else "analysis"
        if kind in get_reporter(name).kinds:
            for options in ({}, {"top": 3}, {"top": 100000}):
                assert render(name, result, options).endswith("\n")


def test_a_lone_surrogate_is_read_as_the_replacement_character() -> None:
    _, base = bases()
    entry = replace(base.new_templates[0], text="bad " + chr(0xD800) + " text")
    result = replace(base, new_templates=(entry,))
    for name in REPORTS:
        text = get_reporter(name).render(result)
        assert "bad" in text
        assert chr(0xD800) not in text


@pytest.mark.parametrize("count", [-5, 2**70])
def test_a_count_outside_the_unsigned_64_bit_range_is_a_config_error(count: int) -> None:
    _, base = bases()
    entry = replace(base.new_templates[0], after_count=count)
    result = replace(base, new_templates=(entry,))
    for name in REPORTS:
        with pytest.raises(ConfigError, match="cannot show"):
            get_reporter(name).render(result)


def test_a_huge_top_keeps_the_size_limit(tmp_path: Path) -> None:
    before, after = hostile_pair(tmp_path)
    diff = logfold.diff(str(before), str(after), format="app", engine="native")
    many = replace(diff, new_templates=diff.new_templates * 400)
    text = get_reporter("github-summary").render(many, top=10**30, max_bytes=5000)
    assert "_Lists are shortened to " in text
    assert len(text.encode("utf-8")) <= 5000


def test_a_short_listing_of_a_hundred_thousand_templates_is_quick() -> None:
    _, base = bases()
    sample = base.new_templates[0]
    many = replace(
        base, new_templates=tuple(replace(sample, text=f"template number {index} <NUM>") for index in range(100_000))
    )
    started = time.perf_counter()
    for name in REPORTS:
        get_reporter(name).render(many)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"{elapsed:.1f}s for four reports of 100 thousand templates"
