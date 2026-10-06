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
    return logfold.diff(*pair, engine="python", min_count=1).to_html()


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
    same = logfold.diff(pair[0], pair[0], engine="python").to_html()
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
    page = logfold.analyze(pair[0], engine="python").to_html()
    match = re.search(r'<table id="templates" class="fx">(<colgroup>.*?</colgroup>)<thead>(.*?)</thead>', page)
    assert match is not None
    assert match.group(1).count("<col") - 1 == match.group(2).count("<th")
    assert page.count('<div class="cards">') == 1


def test_column_widths_come_from_the_stylesheet_not_from_attributes(pair: tuple[Path, Path]) -> None:
    page = diff_html(pair)
    css = page.split("<style>")[1].split("</style>")[0]
    for name in ("wi", "wn", "ws", "wl"):
        assert f".{name}{{width:" in css
    assert "table.fx{table-layout:fixed" in css
    assert "<col style" not in page
