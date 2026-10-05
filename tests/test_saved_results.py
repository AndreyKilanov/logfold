from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
from logfold.cli import exit_codes
from logfold.cli.app import app
from test_diff import synthetic_pair

runner = CliRunner()


def saved_pair(tmp_path: Path, seed: int = 4) -> tuple[Path, Path, Path, Path]:
    before, after, _truth = synthetic_pair(tmp_path, seed)
    first = tmp_path / "before.json"
    second = tmp_path / "after.json"
    logfold.analyze(str(before), format="app").to_json(first)
    logfold.analyze(str(after), format="app").to_json(second)
    return before, after, first, second


def test_analysis_round_trips_through_json(tmp_path: Path) -> None:
    before, _after, saved, _second = saved_pair(tmp_path)
    original = logfold.analyze(str(before), format="app")
    loaded = logfold.load_analysis(saved)
    assert loaded.templates == original.templates
    assert loaded.run == original.run
    assert loaded.meta == original.meta
    assert loaded.metrics.engine == original.metrics.engine


def test_diff_of_saved_results_matches_diff_of_logs(tmp_path: Path) -> None:
    before, after, first, second = saved_pair(tmp_path)
    from_logs = logfold.diff(str(before), str(after), format="app")
    from_saved = logfold.diff(logfold.load_analysis(first), logfold.load_analysis(second))
    assert {e.text for e in from_saved.new_templates} == {e.text for e in from_logs.new_templates}
    assert {e.text for e in from_saved.disappeared} == {e.text for e in from_logs.disappeared}
    assert {e.text for e in from_saved.changed} >= {"cache miss for key <NUM>"}
    assert from_saved.before == from_logs.before
    assert from_saved.after == from_logs.after
    assert any("saved results were mined separately" in w for w in from_saved.warnings)


def test_diff_accepts_results_straight_from_analyze(tmp_path: Path) -> None:
    before, after, _first, _second = saved_pair(tmp_path)
    result = logfold.diff(logfold.analyze(str(before), format="app"), logfold.analyze(str(after), format="app"))
    assert result.new_alerts
    first_new = result.new_templates[0]
    assert first_new.first_seen is not None
    assert first_new.example is not None


def test_diff_of_a_result_with_itself_reports_nothing(tmp_path: Path) -> None:
    _before, _after, first, _second = saved_pair(tmp_path)
    loaded = logfold.load_analysis(first)
    result = logfold.diff(loaded, loaded)
    assert (result.new_templates, result.disappeared, result.changed) == ((), (), ())
    assert result.unchanged == len(loaded.templates)


def test_examples_none_drops_saved_examples(tmp_path: Path) -> None:
    _before, _after, first, second = saved_pair(tmp_path)
    result = logfold.diff(logfold.load_analysis(first), logfold.load_analysis(second), examples="none")
    assert result.new_templates
    assert all(e.example is None for e in result.new_templates)


def test_matcher_pairs_templates_of_separate_runs(tmp_path: Path) -> None:
    specific = tmp_path / "specific.log"
    specific.write_text("".join(f"2026-10-04T12:00:{i:02d}Z INFO user alice failed\n" for i in range(30)), "utf-8")
    general = tmp_path / "general.log"
    general.write_text("".join(f"2026-10-04T12:00:{i:02d}Z INFO user u{i % 5} failed\n" for i in range(30)), "utf-8")
    one = logfold.analyze(str(specific), format="app", masks=[])
    two = logfold.analyze(str(general), format="app", masks=[])
    assert len(logfold.diff(one, two).new_templates) == 1
    merged = logfold.diff(one, two, matcher="token_subset")
    assert (merged.new_templates, merged.disappeared) == ((), ())


def test_different_mining_parameters_are_warned_about(tmp_path: Path) -> None:
    before, after, _first, _second = saved_pair(tmp_path)
    one = logfold.analyze(str(before), format="app")
    two = logfold.analyze(str(after), format="app", sim_th=0.7)
    result = logfold.diff(one, two)
    assert any("different masks or parameters" in w for w in result.warnings)


def test_mining_options_are_rejected_for_saved_results(tmp_path: Path) -> None:
    _before, _after, first, second = saved_pair(tmp_path)
    one, two = logfold.load_analysis(first), logfold.load_analysis(second)
    with pytest.raises(logfold.ConfigError, match="format, masks"):
        logfold.diff(one, two, format="app", masks=[])
    with pytest.raises(logfold.ConfigError, match="not one of each"):
        logfold.diff(one, str(first))


def test_different_algorithm_versions_cannot_be_compared(tmp_path: Path) -> None:
    _before, _after, first, second = saved_pair(tmp_path)
    one, two = logfold.load_analysis(first), logfold.load_analysis(second)
    old = dataclasses.replace(two, meta=dataclasses.replace(two.meta, algo_version=99))
    with pytest.raises(logfold.ConfigError, match="algorithm versions"):
        logfold.diff(one, old)


def test_truncated_and_foreign_reports_are_rejected(tmp_path: Path) -> None:
    before, after, first, _second = saved_pair(tmp_path)
    limited = tmp_path / "limited.json"
    logfold.analyze(str(before), format="app").to_json(limited, limit=1)
    with pytest.raises(logfold.SourceError, match="written with a limit"):
        logfold.load_analysis(limited)
    diff_report = tmp_path / "diff.json"
    logfold.diff(str(before), str(after), format="app").to_json(diff_report)
    with pytest.raises(logfold.SourceError, match="kind 'diff'"):
        logfold.load_analysis(diff_report)
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    with pytest.raises(logfold.SourceError, match="cannot read"):
        logfold.load_analysis(broken)
    with pytest.raises(logfold.SourceError, match="cannot read"):
        logfold.load_analysis(tmp_path / "missing.json")
    listing = tmp_path / "list.json"
    listing.write_text("[]", encoding="utf-8")
    with pytest.raises(logfold.SourceError, match="not an analysis report"):
        logfold.load_analysis(listing)
    incomplete = tmp_path / "incomplete.json"
    payload = json.loads(first.read_text(encoding="utf-8"))
    del payload["meta"]
    incomplete.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(logfold.SourceError, match="malformed"):
        logfold.load_analysis(incomplete)


def test_cli_diff_of_saved_reports(tmp_path: Path) -> None:
    before, after, first, second = saved_pair(tmp_path)
    plain = runner.invoke(app, ["diff", str(first), str(second), "--json"])
    assert plain.exit_code == 0, plain.output
    payload = json.loads(plain.stdout)
    from_logs = json.loads(runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--json"]).stdout)
    assert {e["text"] for e in payload["new_templates"]} == {e["text"] for e in from_logs["new_templates"]}
    gate = runner.invoke(app, ["diff", str(first), str(second), "--fail-on-new"])
    assert gate.exit_code == exit_codes.NEW_TEMPLATES
    html = tmp_path / "saved.html"
    assert runner.invoke(app, ["diff", str(first), str(second), "-o", str(html)]).exit_code == 0
    assert "logfold diff" in html.read_text(encoding="utf-8")


def test_cli_rejects_mining_flags_and_mixed_inputs(tmp_path: Path) -> None:
    before, _after, first, second = saved_pair(tmp_path)
    flags = runner.invoke(app, ["diff", str(first), str(second), "--sim-th", "0.5", "--no-masks"])
    assert flags.exit_code == exit_codes.ERROR
    assert "--sim-th, --no-masks" in flags.output
    mixed = runner.invoke(app, ["diff", str(first), str(before), "-f", "app"])
    assert mixed.exit_code == exit_codes.ERROR
    assert "two saved analysis reports" in mixed.output


def test_jsonl_logs_are_not_mistaken_for_saved_reports(tmp_path: Path) -> None:
    lines = [json.dumps({"level": "info", "message": f"user {i} signed in", "kind": "analysis"}) for i in range(50)]
    log = tmp_path / "events.jsonl"
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = runner.invoke(app, ["diff", str(log), str(log), "-f", "jsonl"])
    assert result.exit_code == 0, result.output
