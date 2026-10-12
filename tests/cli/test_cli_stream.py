"""``logfold stream``: a log is mined while it is read, and each template is printed when it first appears."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from conftest import requires_native
from corpora import app_lines, write
from logfold.cli import exit_codes
from logfold.cli.app import app

pytestmark = requires_native

runner = CliRunner(env={"COLUMNS": "200", "NO_COLOR": "1"})


def feed(lines: list[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def test_standard_input_is_mined_and_each_new_template_is_printed_once() -> None:
    lines = [
        "2026-10-04T00:00:01Z INFO user 1 in",
        "2026-10-04T00:00:02Z INFO user 2 in",
        "2026-10-04T00:00:03Z ERROR boom 5",
    ]
    result = runner.invoke(app, ["stream", "-f", "app", "-q"], input=feed(lines))
    assert result.exit_code == exit_codes.OK, result.output
    assert result.output.count("new  user <NUM> in") == 1
    assert result.output.count("new  boom <NUM>") == 1
    assert "stream: 3 records, 2 templates" in result.output


def test_a_file_is_read_to_its_end_and_json_has_the_analysis_layout(tmp_path: Path) -> None:
    log = write(tmp_path / "app.log", app_lines(800, 4))
    result = runner.invoke(app, ["stream", str(log), "-f", "app", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    document = json.loads(result.output)
    assert document["kind"] == "analysis"
    assert document["run"]["name"] == "stream"
    assert document["run"]["records"] == 800


def test_the_report_of_a_stream_equals_the_report_of_analyze(tmp_path: Path) -> None:
    log = write(tmp_path / "app.log", app_lines(1500, 6))
    streamed = runner.invoke(app, ["stream", str(log), "-f", "app", "--json", "-q", "--batch-size", "37"])
    analyzed = runner.invoke(app, ["analyze", str(log), "-f", "app", "--strategy", "sequential", "--json", "-q"])
    assert streamed.exit_code == analyzed.exit_code == exit_codes.OK
    left = json.loads(streamed.output)["templates"]
    right = json.loads(analyzed.output)["templates"]
    assert left == right


def test_the_state_is_saved_and_analyze_continues_from_it(tmp_path: Path) -> None:
    head = write(tmp_path / "head.log", app_lines(600, 1))
    tail = write(tmp_path / "tail.log", app_lines(300, 2))
    state = tmp_path / "model.json"
    saved = runner.invoke(app, ["stream", str(head), "-f", "app", "--save-state", str(state), "-q"])
    assert saved.exit_code == exit_codes.OK, saved.output
    assert json.loads(state.read_text(encoding="utf-8").splitlines()[0])["kind"] == "logfold-state"
    resumed = runner.invoke(
        app, ["analyze", str(tail), "-f", "app", "--strategy", "sequential", "--load-state", str(state), "--json", "-q"]
    )
    assert resumed.exit_code == exit_codes.OK, resumed.output
    assert json.loads(resumed.output)["run"]["records"] == 300


def test_a_loaded_state_does_not_announce_its_templates(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", app_lines(600, 1))
    state = tmp_path / "model.json"
    assert runner.invoke(app, ["analyze", str(log), "-f", "app", "--save-state", str(state), "-q"]).exit_code == 0
    again = runner.invoke(app, ["stream", str(log), "-f", "app", "--load-state", str(state), "-q"])
    assert again.exit_code == exit_codes.OK, again.output
    assert "new  " not in again.output


def test_control_characters_of_a_template_are_shown_not_acted_on() -> None:
    result = runner.invoke(app, ["stream", "-q"], input=b"\x1b]0;owned\x07 something broke\n")
    assert result.exit_code == exit_codes.OK, result.output
    assert "\x1b" not in result.output
    assert "\\x1b" in result.output


def test_a_multi_line_record_is_joined_by_the_format(tmp_path: Path) -> None:
    lines = ["2026-10-04 boom", "  at frame 1", "2026-10-04 next", "  at frame 2", "  at frame 3"]
    result = runner.invoke(
        app,
        ["stream", "-f", r"regex:^(?P<message>\d{4}-\d\d-\d\d .*)$", "--multiline", "--json", "-q"],
        input=feed(lines),
    )
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(result.output)["run"]["records"] == 2


def test_bytes_that_are_not_utf8_are_replaced() -> None:
    result = runner.invoke(app, ["stream", "--json", "-q"], input=b"caf\xe9 is open\n")
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(result.output)["run"]["records"] == 1


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        (["stream", "-f", "auto"], "no file to detect"),
        (["stream", "--save-every", "5"], "--save-every needs --save-state"),
        (["stream", "missing.log"], "missing.log"),
    ],
)
def test_wrong_use_is_refused_with_the_error_exit_code(arguments: list[str], message: str) -> None:
    result = runner.invoke(app, arguments, input=b"")
    assert result.exit_code == exit_codes.ERROR
    assert message in result.output


def test_a_report_file_can_be_written(tmp_path: Path) -> None:
    out = tmp_path / "report.json"
    result = runner.invoke(app, ["stream", "-o", str(out), "-q"], input=feed(["job 1 done", "job 2 done"]))
    assert result.exit_code == exit_codes.OK, result.output
    assert json.loads(out.read_text(encoding="utf-8"))["run"]["records"] == 2
