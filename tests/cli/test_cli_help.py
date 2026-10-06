from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import typer.main
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app

runner = CliRunner()
PANELS = ("Input", "Output", "Diff", "Mining", "Execution", "General")


def option_params(command: str) -> list[Any]:
    group: Any = typer.main.get_command(app)
    return [
        param
        for param in group.commands[command].params
        if param.opts[0].startswith("-") and "--help" not in param.opts
    ]


@pytest.mark.parametrize("command", ["analyze", "diff"])
def test_every_option_belongs_to_a_panel(command: str) -> None:
    for param in option_params(command):
        assert getattr(param, "rich_help_panel", None) in PANELS, param.opts


def test_the_diff_options_are_only_in_diff() -> None:
    analyze = {panel for param in option_params("analyze") if (panel := param.rich_help_panel)}
    diff = {panel for param in option_params("diff") if (panel := param.rich_help_panel)}
    assert "Diff" not in analyze
    assert set(PANELS) - {"Diff"} <= analyze
    assert set(PANELS) <= diff


@pytest.mark.parametrize("command", ["analyze", "diff"])
def test_help_shows_the_panels_and_examples(command: str) -> None:
    result = runner.invoke(app, [command, "--help"], env={"COLUMNS": "120", "NO_COLOR": "1"})
    assert result.exit_code == exit_codes.OK
    for panel in PANELS:
        if panel == "Diff" and command == "analyze":
            assert "Diff " not in result.stdout.replace("diff", "")
            continue
        assert f" {panel} " in result.stdout
    assert "Examples:" in result.stdout
    assert f"logfold {command} " in result.stdout.split("Examples:")[1]


def test_min_count_help_differs_per_command() -> None:
    analyze = next(p for p in option_params("analyze") if "--min-count" in p.opts)
    diff = next(p for p in option_params("diff") if "--min-count" in p.opts)
    assert analyze.help is not None
    assert diff.help is not None
    assert "Hide templates" in analyze.help
    assert "'changed'" in diff.help
    assert analyze.rich_help_panel == "Output"
    assert diff.rich_help_panel == "Diff"


def test_analyze_shows_the_warning_when_warm_start_did_nothing(corpus_dir: Path) -> None:
    source = str(corpus_dir / "app.log")
    result = runner.invoke(
        app, ["analyze", source, "-f", "app", "--warm-start", "--strategy", "sequential", "--chunk-mb", "8"]
    )
    assert result.exit_code == exit_codes.OK
    assert "warning: warm_start was ignored" in result.stdout
    assert "warning: chunk_bytes was ignored" in result.stdout


def test_an_explicit_chunked_strategy_uses_the_flags(corpus_dir: Path) -> None:
    result = runner.invoke(
        app, ["analyze", str(corpus_dir / "app.log"), "-f", "app", "--strategy", "chunked", "--warm-start"]
    )
    assert result.exit_code == exit_codes.OK
    assert "ignored" not in result.stdout


def test_diff_shows_the_warning_too_and_keeps_its_exit_code(corpus_dir: Path) -> None:
    before, after = corpus_dir / "app_before.log", corpus_dir / "app.log"
    result = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--warm-start"])
    assert result.exit_code == exit_codes.OK
    assert "warning: warm_start was ignored" in result.stdout


def test_inspect_help_has_panels_and_examples() -> None:
    result = runner.invoke(app, ["inspect", "--help"], env={"COLUMNS": "120", "NO_COLOR": "1"})
    assert result.exit_code == exit_codes.OK
    assert "Examples:" in result.stdout
    assert "logfold inspect app.log" in result.stdout
    for param in option_params("inspect"):
        assert param.rich_help_panel in PANELS, param.opts


def test_the_root_help_lists_inspect() -> None:
    assert "inspect" in runner.invoke(app, ["--help"]).stdout
