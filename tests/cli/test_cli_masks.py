"""``--masks``, ``--masks-file``, ``[mining] masks`` and the ``logfold masks`` commands."""

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
LINES = [f"user bob{n}@example.com paid with 4111 1111 1111 1111 token=abcdefgh{n}" for n in range(20)]
SET = {"name": "orders", "rules": [{"name": "order", "pattern": r"\bORD-\d{6}\b", "token": "<ORDER>"}]}


def templates(output: str) -> set[str]:
    return {item["text"] for item in json.loads(output)["templates"]}


def analyze(tmp_path: Path, *extra: str, lines: list[str] | None = None) -> object:
    log = write(tmp_path / "a.log", LINES if lines is None else lines)
    return runner.invoke(app, ["analyze", str(log), "-f", "plain", "--json", "--examples", "none", *extra])


def test_masks_selects_the_built_in_sets(tmp_path: Path) -> None:
    result = analyze(tmp_path, "--masks", "all")
    assert result.exit_code == exit_codes.OK, result.output  # type: ignore[attr-defined]
    assert templates(result.output) == {"user <EMAIL> paid with <CARD> <SECRET>"}  # type: ignore[attr-defined]


def test_without_a_flag_nothing_changes(tmp_path: Path) -> None:
    result = analyze(tmp_path)
    assert result.exit_code == exit_codes.OK  # type: ignore[attr-defined]
    assert "<EMAIL>" not in result.output  # type: ignore[attr-defined]


def test_masks_file_adds_a_set_and_the_flags_combine(tmp_path: Path) -> None:
    path = tmp_path / "orders.json"
    path.write_text(json.dumps(SET), encoding="utf-8")
    lines = [f"order ORD-12345{n % 10} sent to bob{n}@example.com" for n in range(12)]
    result = analyze(tmp_path, "--masks", "pii", "--masks-file", str(path), lines=lines)
    assert result.exit_code == exit_codes.OK, result.output  # type: ignore[attr-defined]
    assert templates(result.output) == {"order <ORDER> sent to <EMAIL>"}  # type: ignore[attr-defined]


def test_no_masks_cannot_be_combined_with_the_set_flags(tmp_path: Path) -> None:
    result = analyze(tmp_path, "--no-masks", "--masks", "pii")
    assert result.exit_code != exit_codes.OK  # type: ignore[attr-defined]
    assert "--no-masks cannot be combined" in result.output  # type: ignore[attr-defined]


def test_a_wrong_name_is_an_error_with_a_suggestion(tmp_path: Path) -> None:
    result = analyze(tmp_path, "--masks", "secret")
    assert result.exit_code != exit_codes.OK  # type: ignore[attr-defined]
    assert "unknown mask set 'secret'" in result.output  # type: ignore[attr-defined]
    assert "secrets" in result.output  # type: ignore[attr-defined]


def test_empty_names_and_bad_files_are_errors(tmp_path: Path) -> None:
    assert analyze(tmp_path, "--masks", "pii,").exit_code != exit_codes.OK  # type: ignore[attr-defined]
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    result = analyze(tmp_path, "--masks-file", str(bad))
    assert result.exit_code != exit_codes.OK  # type: ignore[attr-defined]
    assert "bad.json" in result.output  # type: ignore[attr-defined]
    missing = analyze(tmp_path, "--masks-file", str(tmp_path / "nope.json"))
    assert missing.exit_code != exit_codes.OK  # type: ignore[attr-defined]


def test_the_raw_examples_note_is_shown_only_when_it_matters(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", LINES)
    base = ["analyze", str(log), "-f", "plain", "--json"]
    note = "still the raw lines"
    assert note in runner.invoke(app, [*base, "--masks", "pii"]).output
    assert note not in runner.invoke(app, [*base, "--masks", "pii", "--examples", "masked"]).output
    assert note not in runner.invoke(app, [*base, "--masks", "pii", "-q"]).output
    assert note not in runner.invoke(app, base).output


def test_the_settings_file_names_the_sets_and_the_flag_wins(tmp_path: Path) -> None:
    config = tmp_path / "logfold.toml"
    config.write_text('[mining]\nmasks = ["pii", "payment"]\n', encoding="utf-8")
    log = write(tmp_path / "a.log", LINES)
    base = ["--config", str(config), "analyze", str(log), "-f", "plain", "--json", "--examples", "none", "-q"]
    from_file = runner.invoke(app, base)
    assert from_file.exit_code == exit_codes.OK, from_file.output
    assert all("<EMAIL>" in text and "<CARD>" in text for text in templates(from_file.output))
    flag = runner.invoke(app, [*base, "--masks", "credentials"])
    assert flag.exit_code == exit_codes.OK, flag.output
    assert all("<SECRET>" in text and "<EMAIL>" not in text for text in templates(flag.output))


def test_an_unknown_name_in_the_settings_file_is_reported_when_the_run_starts(tmp_path: Path) -> None:
    config = tmp_path / "logfold.toml"
    config.write_text('[mining]\nmasks = ["nope"]\n', encoding="utf-8")
    log = write(tmp_path / "a.log", LINES)
    result = runner.invoke(app, ["--config", str(config), "analyze", str(log), "-f", "plain", "-q"])
    assert result.exit_code != exit_codes.OK
    assert "unknown mask set 'nope'" in result.output


def test_match_stream_and_params_take_the_flags(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", LINES)
    state = tmp_path / "model.json"
    saved = runner.invoke(
        app,
        ["analyze", str(log), "-f", "plain", "--masks", "pii", "--save-state", str(state), "--examples", "none", "-q"],
    )
    assert saved.exit_code == exit_codes.OK, saved.output
    matched = runner.invoke(
        app, ["match", str(state), str(log), "-f", "plain", "--masks", "pii", "--examples", "none", "--json", "-q"]
    )
    assert matched.exit_code == exit_codes.OK, matched.output
    assert json.loads(matched.output)["run"]["unmatched"]["records"] == 0
    refused = runner.invoke(app, ["match", str(state), str(log), "-f", "plain", "-q"])
    assert refused.exit_code != exit_codes.OK
    streamed = runner.invoke(
        app,
        ["stream", "-f", "plain", "--masks", "pii", "--examples", "masked", "-q"],
        input=("\n".join(LINES) + "\n").encode("utf-8"),
    )
    assert streamed.exit_code == exit_codes.OK, streamed.output
    assert "<EMAIL>" in streamed.output
    values = runner.invoke(app, ["params", "user <EMAIL> ok", "user bob@example.com ok", "--masks", "pii", "--json"])
    assert values.exit_code == exit_codes.OK, values.output
    assert json.loads(values.output)["parameters"] == [{"position": 1, "name": "email", "value": "bob@example.com"}]


def test_diff_takes_the_flags_for_logs_and_refuses_them_for_saved_reports(tmp_path: Path) -> None:
    before = write(tmp_path / "before.log", LINES)
    refund = "refund issued to zed@example.com on card 5555555555554444 ok"
    after = write(tmp_path / "after.log", [*LINES, refund])
    diff = runner.invoke(
        app,
        [
            "diff",
            str(before),
            str(after),
            "-f",
            "plain",
            "--masks",
            "pii,payment",
            "--examples",
            "masked",
            "--json",
            "-q",
        ],
    )
    assert diff.exit_code == exit_codes.OK, diff.output
    assert any("<CARD>" in item["text"] for item in json.loads(diff.output)["new_templates"])
    saved = [tmp_path / "one.json", tmp_path / "two.json"]
    for log, out in zip((before, after), saved, strict=True):
        assert runner.invoke(app, ["analyze", str(log), "-f", "plain", "-o", str(out), "-q"]).exit_code == 0
    refused = runner.invoke(app, ["diff", str(saved[0]), str(saved[1]), "--masks", "pii", "-q"])
    assert refused.exit_code != exit_codes.OK
    assert "--masks" in refused.output


def test_masks_list_and_show(tmp_path: Path) -> None:
    listing = runner.invoke(app, ["masks", "list"])
    assert listing.exit_code == exit_codes.OK, listing.output
    for name in ("default", "secrets", "credentials", "pii", "payment"):
        assert name in listing.output
    data = json.loads(runner.invoke(app, ["masks", "list", "--json"]).output)
    assert {row["name"] for row in data} >= {"default", "secrets", "credentials", "pii", "payment"}
    assert all(len(row["fingerprint"]) == 16 for row in data)
    shown = runner.invoke(app, ["masks", "show", "payment"])
    assert shown.exit_code == exit_codes.OK, shown.output
    assert "<CARD>" in shown.output
    assert "luhn" in shown.output
    as_json = json.loads(runner.invoke(app, ["masks", "show", "secrets", "--json"]).output)
    assert as_json["name"] == "secrets"
    assert as_json["rules"]
    path = tmp_path / "orders.json"
    path.write_text(json.dumps(SET), encoding="utf-8")
    from_file = runner.invoke(app, ["masks", "show", str(path)])
    assert from_file.exit_code == exit_codes.OK, from_file.output
    assert "<ORDER>" in from_file.output
    assert runner.invoke(app, ["masks", "show", "nope"]).exit_code != exit_codes.OK
    assert runner.invoke(app, ["masks", "show", str(tmp_path / "missing.json")]).exit_code != exit_codes.OK


def test_info_and_the_plugin_commands_know_the_mask_kind(tmp_path: Path) -> None:
    assert "mask sets: credentials, default, payment, pii, secrets" in runner.invoke(app, ["info"]).output
    listed = runner.invoke(app, ["plugins", "list", "--kind", "mask", "--installed"])
    assert listed.exit_code == exit_codes.OK, listed.output
    assert "secrets" in listed.output
    assert "mask" in listed.output
    shown = runner.invoke(app, ["plugins", "info", "pii", "--kind", "mask"])
    assert shown.exit_code == exit_codes.OK, shown.output
    assert "--masks pii" in shown.output
    created = runner.invoke(app, ["plugins", "new", "mask", "my-set", "--dir", str(tmp_path)])
    assert created.exit_code == exit_codes.OK, created.output
    assert (tmp_path / "my_set.py").is_file()
    assert runner.invoke(app, ["plugins", "new", "mask", "My-Set", "--dir", str(tmp_path)]).exit_code != exit_codes.OK
