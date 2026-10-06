from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import typer.main
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.cli.ignored import ignored_flag_warnings
from logfold.model import RunMetrics

runner = CliRunner()
PANELS = ("Input", "Output", "Diff", "Mining", "Execution", "General")


def metrics(strategy: str, engine: str = "native") -> RunMetrics:
    return RunMetrics(
        engine=engine,
        strategy=strategy,
        threads=1,
        chunks=1,
        wall_total_s=0.0,
        wall_mine_s=0.0,
        wall_merge_s=0.0,
        wall_recount_s=0.0,
        wall_freeze_s=0.0,
    )


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


def test_a_sequential_run_reports_the_chunked_flags_it_ignored() -> None:
    warnings = ignored_flag_warnings(metrics("sequential"), {"--warm-start": True, "--chunk-mb": True})
    assert [warning.split(" was ignored")[0] for warning in warnings] == ["--warm-start", "--chunk-mb"]
    assert all("--strategy chunked" in warning for warning in warnings)


def test_flags_not_given_or_a_chunked_run_have_no_warnings() -> None:
    assert ignored_flag_warnings(metrics("sequential"), {"--warm-start": False, "--chunk-mb": False}) == []
    assert ignored_flag_warnings(metrics("chunked"), {"--warm-start": True, "--chunk-mb": True}) == []


def test_the_python_engine_is_not_told_to_force_chunks() -> None:
    (warning,) = ignored_flag_warnings(metrics("sequential", "python"), {"--chunk-mb": True})
    assert "always sequential" in warning
    assert "--strategy chunked" not in warning


def test_warm_start_on_the_python_engine_is_left_to_the_library_warning() -> None:
    assert ignored_flag_warnings(metrics("sequential", "python"), {"--warm-start": True}) == []


def test_analyze_warns_when_warm_start_did_nothing(corpus_dir: Path) -> None:
    result = runner.invoke(
        app, ["analyze", str(corpus_dir / "app.log"), "-f", "app", "--warm-start", "--chunk-mb", "8"]
    )
    assert result.exit_code == exit_codes.OK
    assert "warning: --warm-start was ignored" in result.stderr
    assert "warning: --chunk-mb was ignored" in result.stderr


def test_quiet_drops_the_ignored_flag_warnings(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["analyze", str(corpus_dir / "app.log"), "-f", "app", "--warm-start", "-q"])
    assert result.exit_code == exit_codes.OK
    assert "ignored" not in result.stderr


def test_an_explicit_chunked_strategy_uses_the_flags(corpus_dir: Path) -> None:
    result = runner.invoke(
        app, ["analyze", str(corpus_dir / "app.log"), "-f", "app", "--strategy", "chunked", "--warm-start"]
    )
    assert result.exit_code == exit_codes.OK
    assert "ignored" not in result.stderr


def test_diff_warns_too_and_keeps_its_exit_code(corpus_dir: Path) -> None:
    before, after = corpus_dir / "app_before.log", corpus_dir / "app.log"
    result = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--chunk-mb", "4"])
    assert result.exit_code == exit_codes.OK
    assert "warning: --chunk-mb was ignored" in result.stderr


def test_inspect_help_has_panels_and_examples() -> None:
    result = runner.invoke(app, ["inspect", "--help"], env={"COLUMNS": "120", "NO_COLOR": "1"})
    assert result.exit_code == exit_codes.OK
    assert "Examples:" in result.stdout
    assert "logfold inspect app.log" in result.stdout
    for param in option_params("inspect"):
        assert param.rich_help_panel in PANELS, param.opts


def test_the_root_help_lists_inspect() -> None:
    assert "inspect" in runner.invoke(app, ["--help"]).stdout
