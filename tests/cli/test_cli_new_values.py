"""``logfold diff --new-values``: the values that only one of the two runs has."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import requires_native
from corpora import write
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def catalog(ids: range) -> list[str]:
    lines = []
    for item in ids:
        lines.extend(f"2026-10-15 10:00:00 INFO added item {item} to the catalog" for _ in range(item % 3 + 1))
    return lines


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    return write(tmp_path / "a.log", catalog(range(1, 41))), write(tmp_path / "b.log", catalog(range(21, 61)))


def test_without_the_flag_there_is_no_section(pair: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "Values that differ" not in result.output


def test_the_new_and_gone_values_are_printed(pair: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--new-values", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "Values that differ (1 templates)" in result.output
    assert "20 new, 20 gone, 20 in both" in result.output
    assert "new:" in result.output
    assert "gone:" in result.output


def test_the_json_report_has_the_changes(pair: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--new-values", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    position = json.loads(result.output)["value_changes"][0]["positions"][0]
    assert (position["new_distinct"], position["gone_distinct"], position["shared_distinct"]) == (20, 20, 20)


def test_the_number_of_compared_templates_is_validated(pair: tuple[Path, Path]) -> None:
    bad = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--new-values", "--values-templates", "0"])
    assert bad.exit_code != exit_codes.OK
    ok = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--new-values", "--values-templates", "1", "-q"])
    assert ok.exit_code == exit_codes.OK, ok.output


def test_examples_none_leaves_out_the_values(pair: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--new-values", "--examples", "none", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "20 new, 20 gone" in result.output
    assert "new:" not in result.output


def test_saved_reports_and_baselines_are_refused_with_a_hint(pair: tuple[Path, Path], tmp_path: Path) -> None:
    saved = [tmp_path / "a.json", tmp_path / "b.json"]
    for log, report in zip(pair, saved, strict=True):
        assert runner.invoke(app, ["analyze", str(log), "--out", str(report), "-q"]).exit_code == exit_codes.OK
    both = runner.invoke(app, ["diff", str(saved[0]), str(saved[1]), "--new-values"])
    assert both.exit_code != exit_codes.OK
    assert "--new-values" in both.output
    baseline = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--baseline", str(pair[0]), "--new-values"])
    assert baseline.exit_code != exit_codes.OK
    assert "baselines" in baseline.output


def test_the_report_files_have_the_section(pair: tuple[Path, Path], tmp_path: Path) -> None:
    for name in ("d.html", "d.md", "d.json", "d.txt"):
        out = tmp_path / name
        result = runner.invoke(app, ["diff", str(pair[0]), str(pair[1]), "--new-values", "--out", str(out), "-q"])
        assert result.exit_code == exit_codes.OK, result.output
        assert "value" in out.read_text(encoding="utf-8").lower()
