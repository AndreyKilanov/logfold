"""``--delimiters``: the flag, its escapes, and the settings file."""

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
STREAM = [f"conn user_id={n} session=s{n % 3}" for n in range(30)]
SPLIT = "conn user id <*> session <*>"
ESCAPED = " \\t\\n\\r_="


def templates(output: str) -> set[str]:
    return {item["text"] for item in json.loads(output)["templates"]}


def test_the_flag_splits_tokens_and_reads_the_escapes(tmp_path: Path) -> None:
    log = write(tmp_path / "kv.log", STREAM)
    base = ["analyze", str(log), "-f", "plain", "--no-masks", "--json", "-q"]
    split = runner.invoke(app, [*base, "--delimiters", ESCAPED])
    assert split.exit_code == exit_codes.OK, split.output
    assert templates(split.output) == {SPLIT}
    plain = runner.invoke(app, base)
    assert templates(plain.output) != {SPLIT}


def test_a_bad_escape_and_an_empty_value_are_errors(tmp_path: Path) -> None:
    log = write(tmp_path / "kv.log", STREAM)
    bad = runner.invoke(app, ["analyze", str(log), "-f", "plain", "--delimiters", "\\q", "-q"])
    assert bad.exit_code != exit_codes.OK
    assert "unknown escape" in bad.output
    empty = runner.invoke(app, ["analyze", str(log), "-f", "plain", "--delimiters", "", "-q"])
    assert empty.exit_code != exit_codes.OK
    assert "delimiters" in empty.output


def test_the_settings_file_gives_them_and_the_flag_wins(tmp_path: Path) -> None:
    config = tmp_path / "logfold.toml"
    config.write_text('[mining]\ndelimiters = " \\t\\n\\r_="\nmasks = "none"\n', encoding="utf-8")
    log = write(tmp_path / "kv.log", STREAM)
    base = ["--config", str(config), "analyze", str(log), "-f", "plain", "--json", "-q"]
    from_file = runner.invoke(app, base)
    assert from_file.exit_code == exit_codes.OK, from_file.output
    assert templates(from_file.output) == {SPLIT}
    flag = runner.invoke(app, [*base, "--delimiters", " \\t\\n\\r"])
    assert flag.exit_code == exit_codes.OK, flag.output
    assert templates(flag.output) != {SPLIT}


def test_match_and_stream_take_the_flag_and_a_state_of_other_delimiters_is_refused(tmp_path: Path) -> None:
    log = write(tmp_path / "kv.log", STREAM)
    state = tmp_path / "model.json"
    delimiters = ["--delimiters", ESCAPED, "--no-masks"]
    saved = runner.invoke(app, ["analyze", str(log), "-f", "plain", *delimiters, "--save-state", str(state), "-q"])
    assert saved.exit_code == exit_codes.OK, saved.output
    matched = runner.invoke(app, ["match", str(state), str(log), "-f", "plain", *delimiters, "--json", "-q"])
    assert matched.exit_code == exit_codes.OK, matched.output
    assert json.loads(matched.output)["run"]["unmatched"]["records"] == 0
    refused = runner.invoke(app, ["match", str(state), str(log), "-f", "plain", "--no-masks", "-q"])
    assert refused.exit_code != exit_codes.OK
    streamed = runner.invoke(
        app, ["stream", "-f", "plain", *delimiters, "-q"], input=("\n".join(STREAM) + "\n").encode("utf-8")
    )
    assert streamed.exit_code == exit_codes.OK, streamed.output
    assert f"new  {SPLIT}" in streamed.output


def test_params_and_diff_take_the_flag(tmp_path: Path) -> None:
    values = runner.invoke(app, ["params", SPLIT, "conn user_id=7 session=z", "--delimiters", ESCAPED])
    assert values.exit_code == exit_codes.OK, values.output
    assert values.output.split() == ["3", "*", "7", "5", "*", "z"]
    no_space = runner.invoke(app, ["params", "a b", "a b", "--delimiters", ","])
    assert no_space.exit_code != exit_codes.OK
    assert "space" in no_space.output
    before = write(tmp_path / "before.log", STREAM)
    after = write(tmp_path / "after.log", [*STREAM, "conn user_id=99 oops=1"])
    base = ["diff", str(before), str(after), "-f", "plain", "--no-masks", "--json", "-q"]
    plain = runner.invoke(app, base)
    split = runner.invoke(app, [*base, "--delimiters", ESCAPED])
    assert plain.exit_code == split.exit_code == exit_codes.OK, (plain.output, split.output)
    assert any("oops" in item["text"] for item in json.loads(plain.output)["new_templates"])
    assert json.loads(split.output)["new_templates"] == []
