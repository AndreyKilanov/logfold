"""``warm_start``: chunks after the first start from a copy of its tree; off by default, not for sequential runs."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
from conftest import requires_native
from logfold.cli.app import app

pytestmark = requires_native

CHUNK = 1 << 20
runner = CliRunner()


def stray_log(tmp_path: Path, lines: int = 300_000) -> Path:
    """Frequent shapes plus a thin stream of rare ones: a cold chunk generalizes the rare ones into stray templates."""
    rng = random.Random(3)
    words = [f"w{chr(97 + i % 26)}{chr(97 + i // 26)}" for i in range(400)]
    verbs = ("Receiving", "Received", "Deleting")
    rows = []
    for _ in range(lines):
        if rng.random() < 0.002:
            picks = [rng.choice(words) for _ in range(6)]
            rows.append("INFO dfs.DataNode: {} {} {} block {} {} {}".format(*picks))
        else:
            picks = [rng.choice(words) for _ in range(4)]
            size = f" size {picks[3]}" if rng.random() < 0.5 else ""
            rows.append(f"INFO dfs.DataNode: {rng.choice(verbs)} block {picks[0]} src {picks[1]} dest {picks[2]}{size}")
    path = tmp_path / "stray.log"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def texts(result: logfold.AnalysisResult) -> list[tuple[str, int]]:
    return [(t.text, t.count) for t in result.templates]


def test_a_warm_start_gives_fewer_stray_templates(tmp_path: Path) -> None:
    path = stray_log(tmp_path)
    cold = logfold.analyze(path, format="plain", strategy="chunked", chunk_bytes=CHUNK, examples="none")
    warm = logfold.analyze(
        path, format="plain", strategy="chunked", chunk_bytes=CHUNK, examples="none", warm_start=True
    )
    assert len(warm.templates) < len(cold.templates)
    assert warm.run.records == cold.run.records
    assert sum(t.count for t in warm.templates) == warm.run.records


def test_a_warm_start_does_not_depend_on_the_thread_count(tmp_path: Path) -> None:
    path = stray_log(tmp_path, 120_000)
    runs = [
        logfold.analyze(
            path, format="plain", strategy="chunked", chunk_bytes=CHUNK, threads=n, examples="none", warm_start=True
        )
        for n in (1, 4)
    ]
    assert texts(runs[0]) == texts(runs[1])


def test_a_warm_start_is_off_by_default(tmp_path: Path) -> None:
    assert logfold.ExecutionConfig().warm_start is False
    path = stray_log(tmp_path, 120_000)
    default = logfold.analyze(path, format="plain", strategy="chunked", chunk_bytes=CHUNK, examples="none")
    explicit = logfold.analyze(
        path, format="plain", strategy="chunked", chunk_bytes=CHUNK, examples="none", warm_start=False
    )
    assert texts(default) == texts(explicit)


def test_a_warm_start_does_not_touch_the_sequential_strategy(tmp_path: Path) -> None:
    path = stray_log(tmp_path, 60_000)
    plain = logfold.analyze(path, format="plain", strategy="sequential", examples="none")
    warm = logfold.analyze(path, format="plain", strategy="sequential", examples="none", warm_start=True)
    assert texts(plain) == texts(warm)


def test_the_cli_flag_enables_it(tmp_path: Path) -> None:
    path = stray_log(tmp_path)
    base = ["analyze", str(path), "-f", "plain", "--strategy", "chunked", "--chunk-mb", "1", "--json", "-q"]
    cold = json.loads(runner.invoke(app, base).stdout)
    warm = json.loads(runner.invoke(app, [*base, "--warm-start"]).stdout)
    assert len(warm["templates"]) < len(cold["templates"])


def test_saved_reports_refuse_the_flag(tmp_path: Path) -> None:
    path = stray_log(tmp_path, 20_000)
    report = tmp_path / "a.json"
    assert runner.invoke(app, ["analyze", str(path), "-f", "plain", "-q", "--out", str(report)]).exit_code == 0
    refused = runner.invoke(app, ["diff", str(report), str(report), "--warm-start"])
    assert refused.exit_code != 0
    assert "--warm-start" in refused.output


def test_saved_results_refuse_the_keyword(tmp_path: Path) -> None:
    path = stray_log(tmp_path, 20_000)
    result = logfold.analyze(path, format="plain")
    with pytest.raises(logfold.ConfigError):
        logfold.diff(result, result, warm_start=True)


def test_the_pure_python_engine_says_that_it_ignores_the_option(tmp_path: Path) -> None:
    path = stray_log(tmp_path, 2_000)
    result = logfold.analyze(path, format="plain", engine="python", warm_start=True, examples="none")
    assert result.metrics.strategy == "sequential"
    assert any("warm_start was ignored" in warning and "python engine" in warning for warning in result.warnings)
