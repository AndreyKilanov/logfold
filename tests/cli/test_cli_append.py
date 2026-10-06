"""--append: several reports in one file, as in $GITHUB_STEP_SUMMARY, and the library's save(append=True)."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
from logfold.cli import exit_codes
from logfold.cli.app import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


@pytest.fixture
def logs(tmp_path: Path) -> tuple[Path, Path]:
    before = tmp_path / "before.log"
    after = tmp_path / "after.log"
    before.write_text("\n".join(f"INFO request {i} served" for i in range(30)) + "\n", encoding="utf-8")
    after.write_text(
        "\n".join(f"INFO request {i} served" for i in range(30))
        + "\n"
        + "\n".join(f"ERROR payment {i} failed" for i in range(5))
        + "\n",
        encoding="utf-8",
    )
    return before, after


def diff_args(logs: tuple[Path, Path], out: Path, *extra: str) -> list[str]:
    return ["diff", str(logs[0]), str(logs[1]), "-f", "plain", "--out", str(out), "-q", *extra]


def test_append_creates_the_file(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    result = runner.invoke(app, diff_args(logs, out, "--append"))
    assert result.exit_code == 0, result.output
    assert out.read_text(encoding="utf-8").startswith("# ")


def test_a_second_report_is_a_separate_section(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    out.write_text("## Earlier step\nsome text without a newline at the end", encoding="utf-8")
    assert runner.invoke(app, diff_args(logs, out, "--append")).exit_code == 0
    assert runner.invoke(app, diff_args(logs, out, "--append")).exit_code == 0
    text = out.read_text(encoding="utf-8")
    assert text.startswith("## Earlier step\nsome text without a newline at the end\n\n# ")
    assert text.count("\n\n# ") == 2
    assert text.endswith("\n")
    assert text.count("New templates") == 2


def test_without_append_the_file_is_replaced(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    out.write_text("old content", encoding="utf-8")
    assert runner.invoke(app, diff_args(logs, out)).exit_code == 0
    assert "old content" not in out.read_text(encoding="utf-8")


def test_the_report_is_written_before_the_gate_fails(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    result = runner.invoke(app, diff_args(logs, out, "--append", "--fail-on-new"))
    assert result.exit_code == exit_codes.NEW_TEMPLATES
    assert "payment" in out.read_text(encoding="utf-8")


def test_analyze_appends_too(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.txt"
    args = ["analyze", str(logs[0]), "-f", "plain", "--out", str(out), "--append", "-q"]
    assert runner.invoke(app, args).exit_code == 0
    assert runner.invoke(app, args).exit_code == 0
    assert out.read_text(encoding="utf-8").count("request <NUM> served") == 2


@pytest.mark.parametrize("name", ["report.html", "report.json", "report.csv"])
def test_whole_document_reports_refuse_append(logs: tuple[Path, Path], tmp_path: Path, name: str) -> None:
    out = tmp_path / name
    result = runner.invoke(app, diff_args(logs, out, "--append"))
    assert result.exit_code == exit_codes.ERROR
    assert "cannot be appended" in result.output
    assert not out.exists()


def test_append_needs_out(logs: tuple[Path, Path]) -> None:
    result = runner.invoke(app, ["diff", str(logs[0]), str(logs[1]), "-f", "plain", "--append"])
    assert result.exit_code == exit_codes.ERROR
    assert "--append needs --out" in result.output


def test_the_report_option_decides_what_may_be_appended(logs: tuple[Path, Path], tmp_path: Path) -> None:
    out = tmp_path / "summary.txt"
    assert runner.invoke(app, diff_args(logs, out, "--append", "--report", "markdown")).exit_code == 0
    refused = runner.invoke(app, diff_args(logs, out, "--append", "--report", "json"))
    assert refused.exit_code == exit_codes.ERROR


def test_the_library_appends(logs: tuple[Path, Path], tmp_path: Path) -> None:
    result = logfold.diff(logs[0], logs[1], format="plain")
    out = tmp_path / "summary.md"
    result.save(out, append=True)
    result.save(out, append=True)
    assert out.read_text(encoding="utf-8").count("\n\n# ") == 1
    result.save(out)
    assert out.read_text(encoding="utf-8").count("New templates") == 1
    with pytest.raises(logfold.ConfigError, match="cannot be appended"):
        result.save(tmp_path / "x.json", append=True)
    analysis = logfold.analyze(logs[0], format="plain")
    analysis.save(out, append=True)
    assert out.read_text(encoding="utf-8").count("\n\n# ") == 1
