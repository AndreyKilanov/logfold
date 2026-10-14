"""``logfold analyze --values``: the values at the variable positions of the most frequent templates."""

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


@pytest.fixture
def access_log(tmp_path: Path) -> Path:
    lines = [f"GET /{['home', 'login', 'cart'][n % 3]} {404 if n % 10 == 0 else 200} {1 + n % 100}" for n in range(900)]
    lines.extend(f"worker w{n % 3} restarted after {10 + n % 7} seconds idle" for n in range(60))
    return write(tmp_path / "access.log", lines)


def test_without_the_flag_there_are_no_values(access_log: Path) -> None:
    result = runner.invoke(app, ["analyze", str(access_log), "-f", "plain", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert all("values" not in template for template in json.loads(result.output)["templates"])


def test_the_values_are_printed_under_the_templates(access_log: Path) -> None:
    result = runner.invoke(app, ["analyze", str(access_log), "-f", "plain", "--values", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "200 x810" in result.output
    assert "404 x90" in result.output
    assert "numbers (900): min 1" in result.output


def test_the_json_report_has_the_values(access_log: Path) -> None:
    result = runner.invoke(app, ["analyze", str(access_log), "-f", "plain", "--values", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    tracked = [template for template in json.loads(result.output)["templates"] if "values" in template]
    assert len(tracked) == 2
    assert tracked[0]["values"][1]["top"][0] == {"value": "200", "count": 810}


def test_only_the_asked_number_of_templates_is_tracked(access_log: Path) -> None:
    result = runner.invoke(
        app, ["analyze", str(access_log), "-f", "plain", "--values", "--values-templates", "1", "--json", "-q"]
    )
    assert result.exit_code == exit_codes.OK, result.output
    assert sum("values" in template for template in json.loads(result.output)["templates"]) == 1
    bad = runner.invoke(app, ["analyze", str(access_log), "-f", "plain", "--values", "--values-templates", "0"])
    assert bad.exit_code != exit_codes.OK


def test_the_html_report_has_a_values_block(access_log: Path, tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    result = runner.invoke(app, ["analyze", str(access_log), "-f", "plain", "--values", "-o", str(out), "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "<summary>values</summary>" in out.read_text(encoding="utf-8")
