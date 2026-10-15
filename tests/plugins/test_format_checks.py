"""Every built-in format says what it was checked on, and the three places that say it agree.

The texts live in ``logfold.plugins.validation``. ``logfold plugins info NAME`` prints them, ``docs/guide.md`` shows
them as a table between two markers, and ``bench/docs/FORMAT_VALIDATION.md`` has a row for each format in its summary.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from logfold.cli.app import app
from logfold.plugins import listing
from logfold.plugins.validation import CHECKS, format_checks, markdown_table

ROOT = Path(__file__).resolve().parents[2]
GUIDE = ROOT / "docs" / "guide.md"
SUMMARY = ROOT / "bench" / "docs" / "FORMAT_VALIDATION.md"
FORMATS = sorted(info.name for info in listing.list_plugins(kind="format", status="built-in"))
runner = CliRunner()


def test_every_built_in_format_has_an_entry_and_no_entry_is_for_another_name() -> None:
    assert sorted(CHECKS) == FORMATS


@pytest.mark.parametrize("name", FORMATS)
def test_the_texts_are_one_line_without_a_table_separator(name: str) -> None:
    item = format_checks(name)
    assert item is not None
    for text in (item.checked, item.not_checked):
        assert text.strip() == text
        assert text
        assert "|" not in text
        assert chr(10) not in text


def test_a_name_that_is_not_built_in_has_no_entry() -> None:
    assert format_checks("traefik") is None


def test_the_guide_table_is_the_one_the_code_writes() -> None:
    text = GUIDE.read_text(encoding="utf-8")
    match = re.search(r"<!-- format-checks:start -->\n(.*?)\n<!-- format-checks:end -->", text, re.DOTALL)
    assert match is not None
    assert match.group(1) == markdown_table(), "run: python -m logfold.plugins.validation, and paste it into the guide"


def test_the_validation_summary_has_a_row_for_every_format() -> None:
    text = SUMMARY.read_text(encoding="utf-8")
    summary = text.split("## Summary", 1)[1].split("\n## ", 1)[0]
    rows = {match.group(1) for match in re.finditer(r"^\| `([^`]+)` \|", summary, re.MULTILINE)}
    assert rows == set(FORMATS)


@pytest.mark.parametrize("name", FORMATS)
def test_plugins_info_prints_what_the_format_was_checked_on(name: str) -> None:
    result = runner.invoke(app, ["plugins", "info", name, "--kind", "format"])
    assert result.exit_code == 0
    assert "checked on:" in result.output
    assert "not checked:" in result.output


def test_plugins_info_json_has_the_two_texts() -> None:
    result = runner.invoke(app, ["plugins", "info", "haproxy", "--json"])
    row = json.loads(result.output)[0]
    item = format_checks("haproxy")
    assert item is not None
    assert (row["checked"], row["not_checked"]) == (item.checked, item.not_checked)


def test_a_reporter_has_no_such_text() -> None:
    result = runner.invoke(app, ["plugins", "info", "markdown", "--json"])
    row = json.loads(result.output)[0]
    assert (row["checked"], row["not_checked"]) == ("", "")
