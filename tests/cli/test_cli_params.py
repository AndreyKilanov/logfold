"""``logfold params``: the values that one message gives to the variable parts of a template."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from conftest import requires_native
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})
TEMPLATE = "user <NUM> logged in from <IP>"
MESSAGE = "user 42 logged in from 10.0.0.1:8080"


def test_the_parameters_are_printed_one_per_line() -> None:
    result = runner.invoke(app, ["params", TEMPLATE, MESSAGE])
    assert result.exit_code == exit_codes.OK, result.output
    assert result.output.splitlines() == ["1\tnum\t42", "5\tip\t10.0.0.1:8080"]


def test_json_output_holds_the_same_parameters() -> None:
    result = runner.invoke(app, ["params", "login failed for <*>", "login failed for alice", "--json"])
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(result.output) == {"parameters": [{"position": 3, "name": "*", "value": "alice"}]}


def test_a_message_that_does_not_fit_is_an_error_with_a_hint() -> None:
    result = runner.invoke(app, ["params", TEMPLATE, "user 42 logged out"])
    assert result.exit_code == exit_codes.ERROR
    assert "does not fit the template" in result.output
    assert "hint:" in result.output


def test_no_masks_leaves_only_generalized_positions() -> None:
    result = runner.invoke(app, ["params", "id 5 is <*>", "id 5 is fine", "--no-masks"])
    assert result.exit_code == exit_codes.OK, result.output
    assert result.output.splitlines() == ["3\t*\tfine"]


def test_the_masks_of_a_settings_file_apply(tmp_path: Path) -> None:
    settings = tmp_path / "logfold.toml"
    settings.write_text('[mining]\nmasks = "none"\n', encoding="utf-8")
    result = runner.invoke(app, ["--config", str(settings), "params", "id 5 is <*>", "id 5 is fine"])
    assert result.exit_code == exit_codes.OK, result.output
    assert result.output.splitlines() == ["3\t*\tfine"]


def test_control_characters_of_a_value_are_shown_not_acted_on() -> None:
    result = runner.invoke(app, ["params", "run <*>", "run \x1b]0;owned\x07"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "\x1b" not in result.output
    assert r"\x1b" in result.output


def test_a_template_with_nothing_variable_prints_nothing() -> None:
    result = runner.invoke(app, ["params", "service started", "service started"])
    assert result.exit_code == exit_codes.OK, result.output
    assert result.output == ""
