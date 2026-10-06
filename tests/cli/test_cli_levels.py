from __future__ import annotations

import dataclasses
import io
import json
from pathlib import Path

import pytest
from rich.console import Console
from typer.testing import CliRunner

import logfold
from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.cli.levels import filter_analysis, filter_diff, resolve_level
from logfold.cli.render import print_analysis, print_diff
from logfold.errors import ConfigError

runner = CliRunner()
SEVERITY = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"]


def templates(stdout: str) -> list[dict[str, object]]:
    return json.loads(stdout)["templates"]


def test_resolve_level() -> None:
    assert resolve_level(None, False) is None
    assert resolve_level(None, True) == "WARN"
    assert resolve_level("error", False) == "ERROR"
    assert resolve_level("Warning", False) == "WARN"


def test_resolve_level_rejects_a_misspelling_with_a_hint() -> None:
    with pytest.raises(ConfigError, match="unknown level 'erro'") as caught:
        resolve_level("erro", False)
    assert caught.value.hint == "did you mean 'ERROR'?"


def test_level_and_only_alerts_cannot_be_combined() -> None:
    with pytest.raises(ConfigError, match="cannot be combined") as caught:
        resolve_level("ERROR", True)
    assert caught.value.hint is not None
    assert "--level WARN" in caught.value.hint


def test_analyze_keeps_only_templates_at_or_above_the_level(corpus_dir: Path) -> None:
    source = str(corpus_dir / "app.log")
    everything = runner.invoke(app, ["analyze", source, "-f", "app", "--json", "-q"])
    result = runner.invoke(app, ["analyze", source, "-f", "app", "--level", "WARN", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    kept = templates(result.stdout)
    assert 0 < len(kept) < len(templates(everything.stdout))
    assert {t["level"] for t in kept} <= {"WARN", "ERROR", "FATAL"}


def test_only_alerts_is_level_warn(corpus_dir: Path) -> None:
    source = str(corpus_dir / "app.log")
    alerts = runner.invoke(app, ["analyze", source, "-f", "app", "--only-alerts", "--json", "-q"])
    warn = runner.invoke(app, ["analyze", source, "-f", "app", "--level", "warn", "--json", "-q"])
    assert templates(alerts.stdout) == templates(warn.stdout)


def test_a_higher_level_keeps_fewer_templates(corpus_dir: Path) -> None:
    source = str(corpus_dir / "app.log")
    counts = []
    for level in SEVERITY:
        result = runner.invoke(app, ["analyze", source, "-f", "app", "--level", level, "--json", "-q"])
        counts.append(len(templates(result.stdout)))
    assert counts == sorted(counts, reverse=True)
    assert counts[-1] == 0


def test_the_note_says_how_much_was_hidden_and_quiet_drops_it(corpus_dir: Path) -> None:
    source = str(corpus_dir / "app.log")
    noisy = runner.invoke(app, ["analyze", source, "-f", "app", "--level", "ERROR"])
    assert "showing " in noisy.stderr
    assert " templates at ERROR or above" in noisy.stderr
    quiet = runner.invoke(app, ["analyze", source, "-f", "app", "--level", "ERROR", "-q"])
    assert "showing" not in quiet.stderr


def test_a_json_file_stays_complete_with_a_level_filter(corpus_dir: Path, tmp_path: Path) -> None:
    source = str(corpus_dir / "app.log")
    out = tmp_path / "result.json"
    result = runner.invoke(app, ["analyze", source, "-f", "app", "--level", "ERROR", "-o", str(out), "-q"])
    assert result.exit_code == exit_codes.OK
    saved = logfold.load_analysis(out)
    assert {t.level for t in saved.templates} > {"ERROR"}


def test_level_and_min_count_work_together(corpus_dir: Path) -> None:
    source = str(corpus_dir / "app.log")
    result = runner.invoke(
        app, ["analyze", source, "-f", "app", "--level", "INFO", "--min-count", "100", "--json", "-q"]
    )
    kept = templates(result.stdout)
    assert kept
    assert all(t["count"] >= 100 and t["level"] in {"INFO", "WARN", "ERROR", "FATAL"} for t in kept)  # type: ignore[operator]


def test_a_format_without_levels_is_an_error_with_a_hint(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["analyze", str(corpus_dir / "nginx.log"), "-f", "nginx", "--only-alerts"])
    assert result.exit_code == exit_codes.ERROR
    assert "cannot filter by level" in result.stderr
    assert "hint:" in result.stderr


def test_a_bad_level_fails_before_the_log_is_read(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path / "missing.log"), "--level", "loud"])
    assert result.exit_code == exit_codes.ERROR
    assert "unknown level 'loud'" in result.stderr
    assert "cannot read" not in result.stderr


def diff_json(corpus_dir: Path, *extra: str) -> dict[str, object]:
    args = ["diff", str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), "-f", "app", "--json", "-q"]
    result = runner.invoke(app, [*args, *extra])
    return json.loads(result.stdout)


def test_diff_lists_only_templates_at_or_above_the_level(corpus_dir: Path) -> None:
    full = diff_json(corpus_dir)
    errors = diff_json(corpus_dir, "--level", "ERROR")
    for key in ("new_templates", "disappeared", "changed"):
        assert {e["level"] for e in errors[key]} <= {"ERROR", "FATAL"}  # type: ignore[attr-defined]
    assert len(errors["changed"]) < len(full["changed"])  # type: ignore[arg-type]
    assert errors["summary"]["unchanged"] == full["summary"]["unchanged"]  # type: ignore[index]
    assert errors["summary"]["changed"] == len(errors["changed"])  # type: ignore[index, arg-type]


def test_the_gates_use_the_filtered_result(corpus_dir: Path) -> None:
    before, after = str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log")
    base = ["diff", before, after, "-f", "app", "-q"]
    assert runner.invoke(app, [*base, "--fail-on-new"]).exit_code == exit_codes.NEW_TEMPLATES
    assert runner.invoke(app, [*base, "--fail-on-new", "--level", "ERROR"]).exit_code == exit_codes.NEW_TEMPLATES
    assert runner.invoke(app, [*base, "--fail-on-new", "--level", "FATAL"]).exit_code == exit_codes.OK
    assert runner.invoke(app, [*base, "--fail-on-new-alerts", "--only-alerts"]).exit_code == exit_codes.NEW_TEMPLATES


def test_diff_of_saved_results_takes_the_filter_too(corpus_dir: Path, tmp_path: Path) -> None:
    before, after = tmp_path / "before.json", tmp_path / "after.json"
    for source, target in (("app_before.log", before), ("app_after.log", after)):
        assert (
            runner.invoke(app, ["analyze", str(corpus_dir / source), "-f", "app", "-o", str(target), "-q"]).exit_code
            == 0
        )
    result = runner.invoke(app, ["diff", str(before), str(after), "--only-alerts", "--json", "-q"])
    assert result.exit_code == exit_codes.OK, result.output
    payload = json.loads(result.stdout)
    assert {e["level"] for e in payload["new_templates"]} <= {"WARN", "ERROR", "FATAL"}


def test_filter_functions_keep_the_run_counters(corpus_dir: Path) -> None:
    analysis = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    kept = filter_analysis(analysis, "ERROR")
    assert kept.run == analysis.run
    assert 0 < len(kept.templates) < len(analysis.templates)
    comparison = logfold.diff(str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app")
    narrowed = filter_diff(comparison, "ERROR")
    assert narrowed.unchanged == comparison.unchanged
    assert narrowed.before == comparison.before
    assert len(narrowed.new_alerts) == len(narrowed.new_templates)


def test_the_filter_functions_refuse_results_without_levels(corpus_dir: Path) -> None:
    analysis = logfold.analyze(str(corpus_dir / "nginx.log"), format="nginx")
    with pytest.raises(ConfigError, match="gives no levels"):
        filter_analysis(analysis, "WARN")
    assert filter_analysis(dataclasses.replace(analysis, templates=()), "WARN").templates == ()


def screen(render, result, top: int) -> str:  # type: ignore[no-untyped-def]
    buffer = io.StringIO()
    render(Console(file=buffer, width=140, color_system=None, highlight=False), result, top)
    return buffer.getvalue()


def test_the_analysis_summary_has_a_levels_line(corpus_dir: Path) -> None:
    analysis = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    text = screen(print_analysis, analysis, 3)
    levels_line = next(line for line in text.splitlines() if line.startswith("levels:"))
    assert (
        levels_line.index("ERROR") < levels_line.index("WARN") < levels_line.index("INFO") < levels_line.index("DEBUG")
    )
    assert "levels:" not in screen(print_analysis, logfold.analyze(str(corpus_dir / "nginx.log"), format="nginx"), 3)


def test_the_hidden_templates_line_says_how_much_it_hides(corpus_dir: Path) -> None:
    analysis = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    text = screen(print_analysis, analysis, 2)
    line = next(line for line in text.splitlines() if "more templates" in line)
    assert f"{len(analysis.templates) - 2} more templates (" in line
    assert "% of records)" in line
    assert f"--top {len(analysis.templates)}" in line
    assert "more templates" not in screen(print_analysis, analysis, len(analysis.templates))


def test_the_diff_tables_say_how_to_see_the_rest(corpus_dir: Path) -> None:
    comparison = logfold.diff(str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app")
    text = screen(print_diff, comparison, 1)
    assert "shows them all" in text or len(comparison.changed) <= 1


def test_a_written_html_report_says_how_to_open_it(corpus_dir: Path, tmp_path: Path) -> None:
    source = str(corpus_dir / "app.log")
    html = runner.invoke(app, ["analyze", source, "-f", "app", "-o", str(tmp_path / "r.html")])
    assert "(open it in a browser)" in html.stderr
    other = runner.invoke(app, ["analyze", source, "-f", "app", "-o", str(tmp_path / "r.json")])
    assert "wrote " in other.stderr
    assert "browser" not in other.stderr
