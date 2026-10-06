"""The time window in the command line: --since, --until and diff --split-at."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})
BASE = datetime(2026, 10, 6)
FORMAT = r"regex:^(?P<ts>\S+) (?P<lvl>[A-Z]+) (?P<msg>.*)$"


def stamp(second: int) -> str:
    return (BASE + timedelta(seconds=second)).strftime("%Y-%m-%dT%H:%M:%S")


def plain(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


@pytest.fixture
def incident(tmp_path: Path) -> Path:
    lines = []
    for i in range(2000):
        lines.append(f"{stamp(i)} INFO request {i} served in {i % 40} ms")
        if i >= 1000 and i % 5 == 0:
            lines.append(f"{stamp(i)} ERROR payment gateway timeout for order {i}")
    path = tmp_path / "incident.log"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_analyze_keeps_only_the_window(incident: Path) -> None:
    result = runner.invoke(
        app,
        ["analyze", str(incident), "-f", FORMAT, "--since", stamp(0), "--until", stamp(500), "--json", "-q"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run"]["records"] == 500
    assert payload["run"]["out_of_range"] == 2000 + 200 - 500
    assert not any("ERROR" in t["text"] for t in payload["templates"])


def test_analyze_without_a_window_is_unchanged(incident: Path) -> None:
    payload = json.loads(runner.invoke(app, ["analyze", str(incident), "-f", FORMAT, "--json", "-q"]).stdout)
    assert payload["run"]["records"] == 2200
    assert payload["run"]["out_of_range"] == 0


def test_a_bad_time_is_a_clean_error_with_a_hint(incident: Path) -> None:
    result = runner.invoke(app, ["analyze", str(incident), "-f", FORMAT, "--since", "yesterday"])
    assert result.exit_code == exit_codes.ERROR
    assert "ISO 8601" in result.stderr
    assert "hint:" in result.stderr


def test_a_format_without_a_time_is_refused(incident: Path) -> None:
    result = runner.invoke(app, ["analyze", str(incident), "-f", "plain", "--since", stamp(0)])
    assert result.exit_code == exit_codes.ERROR
    assert "no timestamp" in result.stderr


def test_diff_split_at_finds_what_started_at_the_cut(incident: Path) -> None:
    result = runner.invoke(app, ["diff", str(incident), "-f", FORMAT, "--split-at", stamp(1000), "-q"])
    assert result.exit_code == 0
    out = plain(result.stdout)
    assert "New templates (1)" in out
    assert "payment gateway timeout for order <NUM>" in out
    assert f"[..., {stamp(1000)})" in out
    assert f"[{stamp(1000)}, ...)" in out


def test_diff_split_at_gates_work_like_two_files(incident: Path) -> None:
    result = runner.invoke(
        app, ["diff", str(incident), "-f", FORMAT, "--split-at", stamp(1000), "--fail-on-new-alerts", "-q"]
    )
    assert result.exit_code == exit_codes.NEW_TEMPLATES
    empty_second_run = runner.invoke(
        app, ["diff", str(incident), "-f", FORMAT, "--split-at", stamp(1000), "--until", stamp(1000), "-q"]
    )
    assert empty_second_run.exit_code == exit_codes.ERROR


def test_diff_split_at_json_has_the_window_counters(incident: Path) -> None:
    result = runner.invoke(app, ["diff", str(incident), "-f", FORMAT, "--split-at", stamp(1000), "--json", "-q"])
    payload = json.loads(result.stdout)
    assert payload["before"]["records"] == 1000
    assert payload["before"]["out_of_range"] == 1200
    assert payload["after"]["records"] == 1200


def test_diff_needs_two_files_or_split_at(incident: Path) -> None:
    result = runner.invoke(app, ["diff", str(incident), "-f", FORMAT])
    assert result.exit_code == exit_codes.ERROR
    assert "--split-at" in result.stderr


def test_split_at_and_a_second_file_exclude_each_other(incident: Path) -> None:
    result = runner.invoke(app, ["diff", str(incident), str(incident), "--split-at", stamp(10)])
    assert result.exit_code == exit_codes.ERROR
    assert "one file" in result.stderr


def test_split_at_is_rejected_for_saved_reports(incident: Path, tmp_path: Path) -> None:
    saved = tmp_path / "a.json"
    runner.invoke(app, ["analyze", str(incident), "-f", FORMAT, "--out", str(saved), "-q"])
    result = runner.invoke(app, ["diff", str(saved), "--split-at", stamp(10)])
    assert result.exit_code == exit_codes.ERROR
    assert "--split-at" in result.stderr
    both = runner.invoke(app, ["diff", str(saved), str(saved), "--since", stamp(10)])
    assert both.exit_code == exit_codes.ERROR
    assert "--since" in both.stderr


def test_a_missing_file_with_split_at_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(app, ["diff", str(tmp_path / "nope.log"), "--split-at", stamp(10)])
    assert result.exit_code == exit_codes.ERROR
    assert "no such file" in result.stderr


def test_help_documents_the_options() -> None:
    analyze = plain(runner.invoke(app, ["analyze", "--help"]).stdout)
    assert "--since" in analyze
    assert "--until" in analyze
    diff = plain(runner.invoke(app, ["diff", "--help"]).stdout)
    for option in ("--since", "--until", "--split-at"):
        assert option in diff
    assert "logfold diff app.log --split-at" in diff
