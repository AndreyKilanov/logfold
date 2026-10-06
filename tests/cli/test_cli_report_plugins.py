"""The CI and notification reports from the command line: --report NAME and the .xml and .prom suffixes."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from prometheus_client.parser import text_string_to_metric_families
from typer.testing import CliRunner

from corpora import hostile_pair
from logfold.cli import exit_codes
from logfold.cli.app import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture
def logs(tmp_path: Path) -> tuple[Path, Path]:
    return hostile_pair(tmp_path)


def diff_args(logs: tuple[Path, Path], *extra: str) -> list[str]:
    return ["diff", str(logs[0]), str(logs[1]), "-f", "app", "-q", *extra]


def test_report_prints_instead_of_the_tables(logs: tuple[Path, Path]) -> None:
    for name, first_line in (("github-summary", "## logfold: "), ("chat-message", "logfold: ")):
        result = runner.invoke(app, diff_args(logs, "--report", name))
        assert result.exit_code == 0, result.output
        assert result.stdout.startswith(first_line)
        assert "new WARN+ template" in result.stdout
        assert "<script>" not in result.stdout.replace("`<script>", "")


def test_the_xml_suffix_writes_junit_and_prom_writes_metrics(logs: tuple[Path, Path], tmp_path: Path) -> None:
    junit = tmp_path / "logfold.xml"
    prom = tmp_path / "logfold.prom"
    assert runner.invoke(app, diff_args(logs, "--out", str(junit))).exit_code == 0
    assert runner.invoke(app, diff_args(logs, "--out", str(prom))).exit_code == 0
    suite = ET.fromstring(junit.read_bytes()).find("testsuite")
    assert suite is not None
    assert int(suite.get("failures", "0")) >= 4
    names = {family.name for family in text_string_to_metric_families(prom.read_text(encoding="utf-8"))}
    assert {"logfold_diff_records", "logfold_diff_templates", "logfold_diff_new_alerts"} <= names


def test_the_gate_still_decides_the_exit_code_and_the_report_is_written_first(
    logs: tuple[Path, Path], tmp_path: Path
) -> None:
    out = tmp_path / "logfold.xml"
    result = runner.invoke(app, diff_args(logs, "--out", str(out), "--fail-on-new-alerts"))
    assert result.exit_code == exit_codes.NEW_TEMPLATES
    assert ET.fromstring(out.read_bytes()).tag == "testsuites"


def test_junit_is_not_an_analysis_report(logs: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["analyze", str(logs[1]), "-f", "app", "--report", "junit", "-q"])
    assert result.exit_code == exit_codes.ERROR
    assert "does not support analysis" in result.output


def test_a_markdown_summary_is_appended_to_one_file(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    for _ in range(2):
        assert (
            runner.invoke(app, diff_args(logs, "--report", "github-summary", "--out", str(out), "--append")).exit_code
            == 0
        )
    assert out.read_text(encoding="utf-8").count("## logfold: ") == 2


def test_help_names_the_new_suffixes() -> None:
    result = runner.invoke(app, ["diff", "--help"])
    assert ".xml" in result.output
    assert ".prom" in result.output
