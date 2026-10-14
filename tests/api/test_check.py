"""``check()``: a log against a saved model; what the model does not know is a finding."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

import logfold
from conftest import requires_native
from corpora import app_lines, write
from logfold import ConfigError, StateError

pytestmark = requires_native

SCHEMA_DIR = Path(__file__).parents[2] / "docs" / "schema"
PANIC = ["2026-10-04T00:00:00Z ERROR kernel panic on node n1 while mounting volume"] * 3
HARMLESS = ["2026-10-04T00:00:00Z INFO brand new harmless message appears here today"] * 2


@pytest.fixture
def model(tmp_path: Path) -> Path:
    log = write(tmp_path / "good.log", app_lines(2000, 3))
    logfold.analyze(str(log), format="app", strategy="sequential", save_state=tmp_path / "model.json")
    return tmp_path / "model.json"


def checked(model: Path, tmp_path: Path, lines: list[str], **options: object) -> logfold.CheckResult:
    log = write(tmp_path / "current.log", lines)
    return logfold.check(model, str(log), format="app", **options)  # type: ignore[arg-type]


def test_a_log_of_the_same_kind_passes(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, app_lines(500, 7))
    assert result.passed
    assert result.findings == ()
    assert result.unmatched.records == 0
    assert result.diff.new_templates == ()
    assert result.diff.before.records == 2000
    assert result.diff.after.records == 500


def test_new_alerts_and_unmatched_records_are_findings(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, app_lines(200, 7) + PANIC + HARMLESS)
    assert not result.passed
    assert [finding.kind for finding in result.findings] == ["unmatched", "new"]
    assert result.unmatched.records == 5
    assert {entry.text for entry in result.diff.new_templates} == {
        "kernel panic on node n1 while mounting volume",
        "brand new harmless message appears here today",
    }
    assert [entry.text for entry in result.diff.new_alerts] == ["kernel panic on node n1 while mounting volume"]
    assert any("check failed" in warning for warning in result.diff.warnings)


def test_the_limit_and_the_gate_can_be_changed_or_switched_off(model: Path, tmp_path: Path) -> None:
    lines = app_lines(200, 7) + PANIC + HARMLESS
    assert [f.kind for f in checked(model, tmp_path, lines, max_unmatched=5).findings] == ["new"]
    assert [f.kind for f in checked(model, tmp_path, lines, max_unmatched="off").findings] == ["new"]
    assert [f.kind for f in checked(model, tmp_path, lines, fail_on="none").findings] == ["unmatched"]
    assert checked(model, tmp_path, lines, max_unmatched=None, fail_on="none").passed
    harmless = checked(model, tmp_path, app_lines(200, 7) + HARMLESS, max_unmatched=None, fail_on="new-alerts")
    assert harmless.passed
    assert [
        f.kind
        for f in checked(model, tmp_path, app_lines(200, 7) + HARMLESS, max_unmatched=None, fail_on="new").findings
    ] == ["new"]


def test_the_new_templates_are_those_of_mining_the_unmatched_records_alone(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, app_lines(200, 7) + PANIC + HARMLESS)
    alone = logfold.analyze(str(write(tmp_path / "alone.log", PANIC + HARMLESS)), format="app")
    assert {(e.id, e.after_count) for e in result.diff.new_templates} == {(t.id, t.count) for t in alone.templates}


def test_the_model_is_only_read(model: Path, tmp_path: Path) -> None:
    before = model.read_bytes()
    checked(model, tmp_path, app_lines(200, 7) + PANIC)
    assert model.read_bytes() == before


def test_disappeared_templates_are_not_reported(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, [line for line in app_lines(300, 7) if " INFO " in line])
    assert result.diff.disappeared == ()
    assert result.passed


def test_a_shifted_share_is_reported_but_is_not_a_finding(tmp_path: Path) -> None:
    even = [f"2026-10-04T00:00:00Z {level} step {n} done" for n in range(1000) for level in ("INFO",)]
    even += [f"2026-10-04T00:00:00Z WARN retry {n} of the call" for n in range(1000)]
    log = write(tmp_path / "good.log", even)
    logfold.analyze(str(log), format="app", strategy="sequential", save_state=tmp_path / "model.json")
    skewed = [line for line in even if " INFO " in line][:50] + [line for line in even if " WARN " in line]
    result = checked(tmp_path / "model.json", tmp_path, skewed, max_unmatched=None)
    assert [entry.text for entry in result.diff.changed] == ["step <NUM> done"]
    assert result.passed


def test_an_empty_log_is_a_finding(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, ["not a log line at all"])
    assert [finding.kind for finding in result.findings] == ["empty"]


def test_a_state_of_other_settings_is_refused(model: Path, tmp_path: Path) -> None:
    with pytest.raises(StateError):
        checked(model, tmp_path, app_lines(50, 7), sim_th=0.8)


def test_a_state_that_evicts_is_refused(tmp_path: Path) -> None:
    log = write(tmp_path / "good.log", app_lines(300, 3))
    logfold.analyze(str(log), format="app", strategy="sequential", on_full="evict", save_state=tmp_path / "model.json")
    with pytest.raises(ConfigError, match="on_full"):
        checked(tmp_path / "model.json", tmp_path, app_lines(50, 7), on_full="evict")


def test_options_are_validated(model: Path, tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="max_unmatched"):
        checked(model, tmp_path, app_lines(50, 7), max_unmatched=101)
    with pytest.raises(ConfigError, match="fail_on"):
        checked(model, tmp_path, app_lines(50, 7), fail_on="sometimes")  # type: ignore[arg-type]


def test_the_settings_file_gives_the_defaults(model: Path, tmp_path: Path) -> None:
    settings = tmp_path / "logfold.toml"
    settings.write_text('[check]\nmax_unmatched = "off"\nfail_on = "none"\n', encoding="utf-8")
    config = logfold.load_config(settings)
    assert checked(model, tmp_path, app_lines(200, 7) + PANIC, config=config).passed
    assert not checked(model, tmp_path, app_lines(200, 7) + PANIC, config=config, fail_on="new-alerts").passed


def test_the_level_filter_keeps_the_findings(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, app_lines(200, 7) + PANIC + HARMLESS)
    shown = result.filter(min_level="WARN")
    assert [entry.level for entry in shown.diff.new_templates] == ["ERROR"]
    assert shown.findings == result.findings


def test_examples_follow_the_mode(model: Path, tmp_path: Path) -> None:
    raw = checked(model, tmp_path, app_lines(200, 7) + PANIC)
    none = checked(model, tmp_path, app_lines(200, 7) + PANIC, examples="none")
    assert raw.diff.new_templates[0].example is not None
    assert none.diff.new_templates[0].example is None


def validator() -> jsonschema.Draft202012Validator:
    resources = [
        (path.name, Resource.from_contents(json.loads(path.read_text(encoding="utf-8"))))
        for path in SCHEMA_DIR.glob("*.schema.json")
    ]
    schema = json.loads((SCHEMA_DIR / "check-v1.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=Registry().with_resources(resources))


def test_the_json_report_matches_its_schema(model: Path, tmp_path: Path) -> None:
    for lines in (app_lines(200, 7), app_lines(200, 7) + PANIC + HARMLESS):
        result = checked(model, tmp_path, lines)
        payload = json.loads(result.to_json())
        validator().validate(payload)
        assert payload["passed"] is result.passed
        assert payload["unmatched"]["records"] == result.unmatched.records
        assert payload["diff"]["summary"]["new"] == len(result.diff.new_templates)


def test_other_reports_are_those_of_the_comparison(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, app_lines(200, 7) + PANIC)
    assert result.render("text") == result.diff.render("text")
    assert "kernel panic" in result.render("github-summary")
    out = tmp_path / "summary.md"
    result.save(out, "github-summary")
    result.save(out, "github-summary", append=True)
    assert out.read_text(encoding="utf-8").count("kernel panic") >= 2


def test_a_time_window_without_records_is_an_empty_check(model: Path, tmp_path: Path) -> None:
    result = checked(model, tmp_path, app_lines(200, 7), since="2030-01-01T00:00:00")
    assert [finding.kind for finding in result.findings] == ["empty"]
    kept = checked(model, tmp_path, app_lines(200, 7), until="2030-01-01T00:00:00")
    assert kept.passed
    assert kept.diff.after.records == 200


def plain_lines(count: int) -> list[str]:
    return [f"user u{n % 7} requested /item/{n} in {n % 90} ms" for n in range(count)]


def test_a_format_without_levels_cannot_raise_an_alert_and_the_result_says_so(tmp_path: Path) -> None:
    log = write(tmp_path / "good.log", plain_lines(2000))
    logfold.analyze(str(log), format="plain", save_state=tmp_path / "model.json")
    odd = ["disk controller reported unrecoverable media error on sector now"] * 10
    current = write(tmp_path / "current.log", plain_lines(1990) + odd)
    gate = logfold.check(tmp_path / "model.json", str(current), format="plain")
    assert gate.passed
    assert any("have no level" in warning for warning in gate.diff.warnings)
    strict = logfold.check(tmp_path / "model.json", str(current), format="plain", fail_on="new")
    assert [finding.kind for finding in strict.findings] == ["new"]
    assert not any("have no level" in warning for warning in strict.diff.warnings)


def test_an_analysis_report_is_not_a_model(tmp_path: Path) -> None:
    log = write(tmp_path / "good.log", app_lines(200, 3))
    report = tmp_path / "report.json"
    logfold.analyze(str(log), format="app").to_json(report)
    with pytest.raises(StateError, match="analysis report") as raised:
        logfold.check(report, str(log), format="app")
    assert "--save-state" in (raised.value.hint or "")
    with pytest.raises(StateError, match="analysis report"):
        logfold.match(report, str(log), format="app")
