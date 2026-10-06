"""Several baselines in the command line: diff --baseline and --min-baselines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def write(path: Path, *parts: str) -> Path:
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def block(count: int, template: str) -> str:
    return "\n".join(template.format(i=i) for i in range(count))


COMMON = "INFO request {i} served from cache in {i} ms"
RETRY = "WARN retrying upstream call attempt {i} after connection reset"
CRASH = "ERROR payment gateway rejected order {i} with status 502"


@pytest.fixture
def logs(tmp_path: Path) -> dict[str, Path]:
    common = block(40, COMMON)
    return {
        "b1": write(tmp_path / "b1.log", common, block(40, RETRY)),
        "b2": write(tmp_path / "b2.log", common),
        "after": write(tmp_path / "after.log", common, block(40, RETRY), block(40, CRASH)),
    }


def run(logs: dict[str, Path], *extra: str) -> dict[str, object]:
    args = ["diff", str(logs["b1"]), str(logs["after"]), "-f", "plain", "--json", "-q", *extra]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)  # type: ignore[no-any-return]


def new_texts(payload: dict[str, object]) -> list[str]:
    return [item["text"] for item in payload["new_templates"]]  # type: ignore[index,attr-defined]


def test_a_baseline_hides_what_it_has(logs: dict[str, Path]) -> None:
    alone = run(logs, "--min-count", "1")
    assert any("payment gateway" in text for text in new_texts(alone))
    pooled = run(logs, "--baseline", str(logs["b2"]), "--min-count", "1")
    assert [t for t in new_texts(pooled) if "retrying" in t] == []
    assert pooled["before"]["records"] == 80 + 40  # type: ignore[index]
    assert pooled["config"]["min_baselines"] is None  # type: ignore[index]


def test_min_baselines_is_reported_in_the_config(logs: dict[str, Path]) -> None:
    pooled = run(logs, "--baseline", str(logs["b2"]), "--min-baselines", "1")
    assert pooled["config"]["min_baselines"] == 1  # type: ignore[index]


def test_the_gate_looks_at_what_no_baseline_has(logs: dict[str, Path], tmp_path: Path) -> None:
    quiet = write(tmp_path / "quiet.log", block(40, COMMON), block(40, RETRY), block(40, CRASH))
    args = ["diff", str(logs["b1"]), str(quiet), "-f", "plain", "--fail-on-new", "-q", "--baseline", str(logs["b2"])]
    assert runner.invoke(app, args).exit_code == exit_codes.NEW_TEMPLATES
    ok = write(tmp_path / "ok.log", block(40, COMMON), block(40, RETRY))
    args[2] = str(ok)
    assert runner.invoke(app, args).exit_code == 0


def test_min_baselines_needs_baselines(logs: dict[str, Path]) -> None:
    result = runner.invoke(app, ["diff", str(logs["b1"]), str(logs["after"]), "--min-baselines", "2"])
    assert result.exit_code == exit_codes.ERROR
    assert "--min-baselines needs --baseline" in result.output


def test_min_baselines_larger_than_the_baselines_is_refused(logs: dict[str, Path]) -> None:
    args = [
        "diff",
        str(logs["b1"]),
        str(logs["after"]),
        "-f",
        "plain",
        "--baseline",
        str(logs["b2"]),
        "--min-baselines",
        "3",
    ]
    result = runner.invoke(app, args)
    assert result.exit_code != 0
    assert "only 2 baselines" in result.output


def test_baselines_are_refused_with_saved_reports_and_split_at(logs: dict[str, Path], tmp_path: Path) -> None:
    saved = tmp_path / "saved.json"
    assert runner.invoke(app, ["analyze", str(logs["b1"]), "-f", "plain", "--out", str(saved), "-q"]).exit_code == 0
    result = runner.invoke(app, ["diff", str(saved), str(saved), "--baseline", str(logs["b2"])])
    assert result.exit_code != 0
    assert "log files only" in result.output
    cut = runner.invoke(app, ["diff", str(logs["b1"]), "--split-at", "2026-10-06T00:00", "--baseline", str(logs["b2"])])
    assert cut.exit_code != 0
    assert "log files only" in cut.output


def test_a_missing_baseline_names_the_file(logs: dict[str, Path], tmp_path: Path) -> None:
    result = runner.invoke(app, ["diff", str(logs["b1"]), str(logs["after"]), "--baseline", str(tmp_path / "gone.log")])
    assert result.exit_code != 0
    assert "gone.log" in result.output
