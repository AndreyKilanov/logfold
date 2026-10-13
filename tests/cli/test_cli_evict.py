"""``--on-full evict``: the flag, the settings file and the errors."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from conftest import requires_native
from corpora import write
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def shapes(count: int) -> list[str]:
    return [f"shape{n}a shape{n}b shape{n}c" for n in range(count)]


def test_analyze_drops_the_least_recently_used_templates_and_says_so(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", shapes(200))
    result = runner.invoke(
        app, ["analyze", str(log), "-f", "plain", "--max-templates", "30", "--on-full", "evict", "--json", "-q"]
    )
    assert result.exit_code == exit_codes.OK, result.output
    report = json.loads(result.output)
    assert report["run"]["evicted"] > 0
    assert sum(item["count"] for item in report["templates"]) == 200
    assert any("least recently used" in warning for warning in report["warnings"])


def test_the_default_does_not_evict(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", shapes(200))
    result = runner.invoke(app, ["analyze", str(log), "-f", "plain", "--max-templates", "30", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "evicted" not in json.loads(result.output)["run"]


def test_an_unknown_value_and_the_chunked_strategy_are_errors(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", shapes(50))
    result = runner.invoke(app, ["analyze", str(log), "-f", "plain", "--on-full", "forget", "-q"])
    assert result.exit_code != exit_codes.OK
    assert "on_full" in result.output
    result = runner.invoke(
        app, ["analyze", str(log), "-f", "plain", "--on-full", "evict", "--strategy", "chunked", "-q"]
    )
    assert result.exit_code != exit_codes.OK
    assert "sequential" in result.output


def test_stream_keeps_learning_after_the_limit() -> None:
    lines = "\n".join(shapes(100)) + "\n"
    result = runner.invoke(
        app,
        ["stream", "-f", "plain", "--max-templates", "20", "--on-full", "evict", "-q"],
        input=lines.encode("utf-8"),
    )
    assert result.exit_code == exit_codes.OK, result.output
    assert "new  shape99a shape99b shape99c" in result.output


def test_a_state_of_the_other_policy_is_refused_by_match(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", shapes(100))
    state = tmp_path / "model.json"
    saved = runner.invoke(
        app,
        [
            "analyze",
            str(log),
            "-f",
            "plain",
            "--max-templates",
            "30",
            "--on-full",
            "evict",
            "--save-state",
            str(state),
            "-q",
        ],
    )
    assert saved.exit_code == exit_codes.OK, saved.output
    refused = runner.invoke(app, ["match", str(state), str(log), "-f", "plain", "--max-templates", "30", "-q"])
    assert refused.exit_code != exit_codes.OK
    accepted = runner.invoke(
        app, ["match", str(state), str(log), "-f", "plain", "--max-templates", "30", "--on-full", "evict", "-q"]
    )
    assert accepted.exit_code == exit_codes.OK, accepted.output


def test_the_settings_file_can_turn_it_on_and_a_flag_wins(tmp_path: Path) -> None:
    config = tmp_path / "logfold.toml"
    config.write_text('[mining]\nmax_templates = 30\non_full = "evict"\n', encoding="utf-8")
    log = write(tmp_path / "a.log", shapes(200))
    base = ["--config", str(config), "analyze", str(log), "-f", "plain", "--json", "-q"]
    from_file = runner.invoke(app, base)
    assert from_file.exit_code == exit_codes.OK, from_file.output
    assert json.loads(from_file.output)["run"]["evicted"] > 0
    flag = runner.invoke(app, [*base, "--on-full", "pool"])
    assert flag.exit_code == exit_codes.OK, flag.output
    assert "evicted" not in json.loads(flag.output)["run"]
