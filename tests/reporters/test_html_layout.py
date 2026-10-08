"""Layout of the HTML report: grouped and colored summary cards, and table columns that line up between tables."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import logfold
from corpora import synthetic_pair


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    before, after, _ = synthetic_pair(tmp_path, 1)
    return before, after


def diff_html(pair: tuple[Path, Path]) -> str:
    return logfold.diff(*pair, engine="native", min_count=1).to_html()


def test_diff_cards_are_two_rows_of_five(pair: tuple[Path, Path]) -> None:
    page = diff_html(pair)
    rows = re.findall(r'<div class="cards c5">(.*?)</div></div>', page)
    assert len(rows) == 2
    labels = [re.findall(r"<span>(.*?)</span>", row) for row in rows]
    assert labels == [
        ["new", "new WARN+", "disappeared", "changed", "unchanged"],
        ["records before", "records after", "format", "engine", "seconds"],
    ]


def test_counts_get_their_color_only_when_there_is_something_to_show(pair: tuple[Path, Path]) -> None:
    page = diff_html(pair)
    for tone, label in (("new", "new"), ("alert", "new WARN+"), ("gone", "disappeared"), ("chg", "changed")):
        assert re.search(rf'<div class="card {tone}"><b>[1-9][\d,]*</b><span>{re.escape(label)}</span>', page), label
    same = logfold.diff(pair[0], pair[0], engine="native").to_html()
    for label in ("new", "new WARN+", "disappeared", "changed"):
        assert f'<div class="card"><b>0</b><span>{label}</span></div>' in same


def test_run_facts_and_unchanged_stay_neutral(pair: tuple[Path, Path]) -> None:
    page = diff_html(pair)
    for label in ("unchanged", "records before", "records after", "format", "engine", "seconds"):
        assert re.search(rf'<div class="card"><b>[^<]*</b><span>{label}</span></div>', page), label


def test_every_diff_table_has_the_same_fixed_columns(pair: tuple[Path, Path]) -> None:
    page = diff_html(pair)
    tables = re.findall(r'<table id="(\w+)" class="fx">(<colgroup>.*?</colgroup>)<thead>(.*?)</thead>', page)
    assert [name for name, _, _ in tables] == ["new", "changed", "gone"]
    assert len({cols for _, cols, _ in tables}) == 1
    for _, cols, head in tables:
        assert cols.count("<col") - 1 == head.count("<th")


def test_the_analysis_table_has_fixed_columns_too(pair: tuple[Path, Path]) -> None:
    page = logfold.analyze(pair[0], engine="native").to_html()
    match = re.search(r'<table id="templates" class="fx">(<colgroup>.*?</colgroup>)<thead>(.*?)</thead>', page)
    assert match is not None
    assert match.group(1).count("<col") - 1 == match.group(2).count("<th")


def test_column_widths_come_from_the_stylesheet_not_from_attributes(pair: tuple[Path, Path]) -> None:
    page = diff_html(pair)
    css = page.split("<style>")[1].split("</style>")[0]
    for name in ("wi", "wn", "ws", "wl"):
        assert f".{name}{{width:" in css
    assert "table.fx{table-layout:fixed" in css
    assert "<col style" not in page


def test_analysis_cards_follow_the_same_two_rows_as_diff(pair: tuple[Path, Path]) -> None:
    page = logfold.analyze(pair[0], engine="native").to_html()
    rows = re.findall(r'<div class="cards c5">(.*?)</div></div>', page)
    assert len(rows) == 2
    labels = [re.findall(r"<span>(.*?)</span>", row) for row in rows]
    assert labels == [
        ["records", "lines", "templates", "WARN+ templates", "unparsed lines"],
        ["format", "engine", "strategy", "threads", "seconds"],
    ]
    assert re.search(r'<div class="card info"><b>[\d,]+</b><span>records</span>', page)
    assert re.search(r'<div class="card alert"><b>[1-9][\d,]*</b><span>WARN\+ templates</span>', page)


def test_analysis_colors_the_unparsed_lines_only_when_there_are_some(tmp_path: Path) -> None:
    clean = tmp_path / "clean.log"
    clean.write_text("2026-10-06T10:00:00Z INFO started\n" * 3, encoding="utf-8")
    page = logfold.analyze(clean, format="app", engine="native").to_html()
    assert '<div class="card"><b>0</b><span>unparsed lines</span></div>' in page
    assert '<div class="card"><b>0</b><span>WARN+ templates</span></div>' in page
    dirty = tmp_path / "dirty.log"
    dirty.write_text("2026-10-06T10:00:00Z INFO started\nnot a record\n", encoding="utf-8")
    page = logfold.analyze(dirty, format="app", engine="native").to_html()
    assert '<div class="card gone"><b>1</b><span>unparsed lines</span></div>' in page


def test_the_page_has_no_style_attributes_that_the_csp_would_block(pair: tuple[Path, Path]) -> None:
    for page in (logfold.analyze(pair[0], engine="native").to_html(), diff_html(pair)):
        assert " style=" not in page.split("</style>", 1)[1]


def test_share_bars_get_their_width_from_a_class(pair: tuple[Path, Path]) -> None:
    page = logfold.analyze(pair[0], engine="native").to_html()
    css = page.split("<style>")[1].split("</style>")[0]
    widths = [int(width) for width in re.findall(r'<span class="bar bw(\d+)"></span>', page)]
    assert widths
    assert all(1 <= width <= 80 for width in widths)
    for width in set(widths):
        assert f".bw{width}{{width:{width}px}}" in css
    assert ".bw1{width:1px}" in css
    assert ".bw80{width:80px}" in css


def test_analysis_has_a_section_heading_like_diff(pair: tuple[Path, Path], tmp_path: Path) -> None:
    result = logfold.analyze(pair[0], engine="native")
    assert f"<h2>Templates ({len(result.templates):,})</h2>" in result.to_html()
    empty = tmp_path / "empty.log"
    empty.write_text("", encoding="utf-8")
    nothing = logfold.analyze(empty, format="plain", engine="native").to_html()
    assert "<h2>Templates (0)</h2>" in nothing
    assert "Nothing to report." in nothing
