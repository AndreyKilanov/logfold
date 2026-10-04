from __future__ import annotations

import errno
import json
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
import logfold.cli.app as cli_app
from logfold.cli import exit_codes
from logfold.cli.app import app
from test_diff import synthetic_pair

runner = CliRunner()


def test_version_and_help() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert logfold.__version__ in result.stdout
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for command in ("analyze", "diff", "formats", "info"):
        assert command in help_result.stdout


def test_analyze_prints_templates(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["analyze", str(corpus_dir / "app.log"), "--top", "3", "--format", "app"])
    assert result.exit_code == exit_codes.OK, result.output
    assert "records" in result.stdout
    assert "template" in result.stdout


def test_analyze_json_to_stdout_is_valid(corpus_dir: Path) -> None:
    result = runner.invoke(app, ["analyze", str(corpus_dir / "app.log"), "--json", "-q", "-f", "app"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["kind"] == "analysis"
    assert payload["run"]["records"] == 1500


@pytest.mark.parametrize("suffix", [".html", ".json", ".txt"])
def test_analyze_writes_reports(corpus_dir: Path, tmp_path: Path, suffix: str) -> None:
    out = tmp_path / f"report{suffix}"
    result = runner.invoke(app, ["analyze", str(corpus_dir / "app.log"), "-f", "app", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert out.stat().st_size > 100


def test_unknown_report_suffix_is_an_error(corpus_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(corpus_dir / "app.log"), "-f", "app", "-o", str(tmp_path / "r.pdf")])
    assert result.exit_code == exit_codes.ERROR
    assert "report format" in result.stderr


def test_errors_exit_with_code_one(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", str(tmp_path / "missing.log"), "-f", "plain"])
    assert result.exit_code == exit_codes.ERROR
    assert "error:" in result.stderr
    bad_format = runner.invoke(app, ["analyze", str(tmp_path / "x.log"), "-f", "nope"])
    assert bad_format.exit_code == exit_codes.ERROR


def test_undetectable_format_is_a_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "free.txt"
    path.write_text("just some words here\n" * 30, encoding="utf-8")
    result = runner.invoke(app, ["analyze", str(path)])
    assert result.exit_code == exit_codes.ERROR
    assert "could not detect" in result.stderr


def test_min_count_hides_rare_templates(corpus_dir: Path) -> None:
    result = runner.invoke(
        app, ["analyze", str(corpus_dir / "noisy.log"), "-f", "plain", "--min-count", "100000", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["templates"] == []


def test_custom_regex_format(tmp_path: Path) -> None:
    path = tmp_path / "c.log"
    path.write_text("<ERR> disk 1 bad\n<ERR> disk 2 bad\n", encoding="utf-8")
    result = runner.invoke(app, ["analyze", str(path), "-f", r"regex:^<(?P<level>\w+)> (?P<message>.*)$", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["templates"][0]["text"] == "disk <NUM> bad"
    assert payload["templates"][0]["level"] == "ERROR"


def test_diff_exit_codes(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 8)
    plain = runner.invoke(app, ["diff", str(before), str(after), "-f", "app"])
    assert plain.exit_code == 0
    assert "New templates" in plain.stdout
    gate = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--fail-on-new"])
    assert gate.exit_code == exit_codes.NEW_TEMPLATES
    alerts = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "--fail-on-new-alerts"])
    assert alerts.exit_code == exit_codes.NEW_TEMPLATES
    same = runner.invoke(app, ["diff", str(before), str(before), "-f", "app", "--fail-on-new"])
    assert same.exit_code == 0


def test_diff_thresholds_can_hide_new(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 8)
    result = runner.invoke(
        app, ["diff", str(before), str(after), "-f", "app", "--fail-on-new", "--min-new-count", "100000", "--json"]
    )
    assert result.exit_code == 0
    assert json.loads(result.stdout)["summary"]["new"] == 0


def test_diff_writes_html(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 10)
    out = tmp_path / "diff.html"
    result = runner.invoke(app, ["diff", str(before), str(after), "-f", "app", "-o", str(out)])
    assert result.exit_code == 0
    assert "logfold diff" in out.read_text(encoding="utf-8")


def test_formats_and_info() -> None:
    formats = runner.invoke(app, ["formats"])
    assert formats.exit_code == 0
    for name in ("nginx", "jsonl", "journald", "app"):
        assert name in formats.stdout
    assert "[T " in formats.stdout or "T " in formats.stdout
    info = runner.invoke(app, ["info"])
    assert info.exit_code == 0
    assert "logfold" in info.stdout
    assert "native engine" in info.stdout


def test_module_entry_point_runs_in_a_subprocess(corpus_dir: Path) -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "logfold", "analyze", str(corpus_dir / "app.log"), "-f", "app", "-q"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    assert "1,500 records" in completed.stdout


def test_subprocess_exit_code_for_gate(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 12)
    completed = subprocess.run(
        [sys.executable, "-m", "logfold", "diff", str(before), str(after), "-f", "app", "--fail-on-new", "-q"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    assert completed.returncode == exit_codes.NEW_TEMPLATES


def test_high_cardinality_flag(tmp_path: Path) -> None:
    import random

    rng = random.Random(1)
    path = tmp_path / "unique.log"
    path.write_text(
        "\n".join(" ".join(f"w{rng.getrandbits(40):x}" for _ in range(8)) for _ in range(9000)) + "\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["analyze", str(path), "-f", "plain", "--high-cardinality", "--json", "-q"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["template_count"] <= 5010
    assert payload["run"]["overflowed"] is True


def test_closed_output_pipe_ends_quietly() -> None:
    script = "import logfold.cli.app as a; a.app = lambda: [print('x' * 100) for _ in range(200_000)]; a.run()"
    child = subprocess.Popen([sys.executable, "-c", script], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert child.stdout is not None
    assert child.stderr is not None
    child.stdout.readline()
    child.stdout.close()
    stderr = child.stderr.read()
    child.stderr.close()
    assert child.wait(timeout=60) == exit_codes.ERROR
    assert stderr == b""


def test_unrelated_os_errors_are_not_swallowed(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail() -> None:
        raise OSError(errno.EACCES, "denied")

    monkeypatch.setattr(cli_app, "app", fail)
    with pytest.raises(OSError, match="denied"):
        cli_app.run()
