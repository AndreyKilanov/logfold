"""The native engine must agree exactly with the pure-Python reference engine (docs/ALGORITHM.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import logfold
from conftest import requires_native
from corpora import CORPORA
from logfold import ExecutionConfig, MaskRule, MiningConfig, _core
from logfold.config import DEFAULT_MASKS

pytestmark = requires_native


def snapshot(result: logfold.AnalysisResult) -> dict[str, Any]:
    run = result.run
    return {
        "counters": (run.files, run.lines, run.records, run.unparsed, run.bytes, run.tz_aware, run.overflowed),
        "templates": [
            (t.id, t.text, t.count, t.first_seen, t.last_seen, t.example, t.level, dict(t.levels))
            for t in result.templates
        ],
    }


def both(paths: str | list[str], **kwargs: Any) -> tuple[logfold.AnalysisResult, logfold.AnalysisResult]:
    native_result = logfold.analyze(paths, engine="native", strategy="sequential", **kwargs)
    python_result = logfold.analyze(paths, engine="python", **kwargs)
    return native_result, python_result


@pytest.mark.parametrize("name", sorted(CORPORA))
def test_corpora_agree(corpus_dir: Path, name: str) -> None:
    _generate, fmt, multiline = CORPORA[name]
    native_result, python_result = both(str(corpus_dir / f"{name}.log"), format=fmt, multiline=multiline or None)
    assert snapshot(native_result) == snapshot(python_result)
    assert native_result.run.records > 0
    assert native_result.meta.config_hash == python_result.meta.config_hash


@pytest.mark.parametrize("name", ["app_crlf.log", "app_nonl.log"])
def test_line_endings_agree(corpus_dir: Path, name: str) -> None:
    native_result, python_result = both(str(corpus_dir / name), format="app")
    assert snapshot(native_result) == snapshot(python_result)
    assert native_result.run.records == 400


@pytest.mark.parametrize(
    "options",
    [
        {"depth": 3},
        {"depth": 6},
        {"depth": 4, "sim_th": 0.0},
        {"depth": 4, "sim_th": 1.0},
        {"depth": 5, "sim_th": 0.7, "max_children": 2},
        {"depth": 4, "max_children": 1},
        {"max_templates": 5},
        {"max_templates": 1},
    ],
)
def test_parameters_agree(corpus_dir: Path, options: dict[str, Any]) -> None:
    native_result, python_result = both(str(corpus_dir / "noisy.log"), format="plain", **options)
    assert snapshot(native_result) == snapshot(python_result)


def test_overflow_is_flagged_identically(corpus_dir: Path) -> None:
    native_result, python_result = both(str(corpus_dir / "noisy.log"), format="plain", max_templates=4)
    assert native_result.run.overflowed
    assert python_result.run.overflowed
    assert sum(t.count for t in native_result.templates) == native_result.run.records


def test_custom_masks_and_delimiters_agree(corpus_dir: Path) -> None:
    mining = MiningConfig(
        delimiters=" \t\n\r,;=",
        masks=(MaskRule("user", r"user [a-z]+", "user <USER>"), MaskRule("num", r"\d+", "<N>", True)),
    )
    native_result, python_result = both(str(corpus_dir / "app.log"), format="app", mining=mining)
    assert snapshot(native_result) == snapshot(python_result)
    assert any("<USER>" in t.text for t in native_result.templates)


def test_multiple_files_form_one_run(corpus_dir: Path) -> None:
    paths = [str(corpus_dir / "app.log"), str(corpus_dir / "app_nonl.log")]
    native_result, python_result = both(paths, format="app")
    assert snapshot(native_result) == snapshot(python_result)
    assert native_result.run.files == 2


def test_diff_agrees(corpus_dir: Path) -> None:
    before = str(corpus_dir / "app_before.log")
    after = str(corpus_dir / "app_after.log")
    native_result = logfold.diff(before, after, engine="native", strategy="sequential", format="app")
    python_result = logfold.diff(before, after, engine="python", format="app")
    for attr in ("new_templates", "disappeared", "changed"):
        assert getattr(native_result, attr) == getattr(python_result, attr), attr
    assert native_result.unchanged == python_result.unchanged
    assert native_result.new_templates or native_result.changed


def test_examples_are_truncated_on_character_boundaries(tmp_path: Path) -> None:
    long_line = "start " + "é" * 3000
    path = tmp_path / "long.log"
    path.write_text(long_line + "\n", encoding="utf-8")
    native_result, python_result = both(str(path), format="plain")
    assert snapshot(native_result) == snapshot(python_result)
    example = native_result.templates[0].example
    assert example is not None
    assert len(example.encode("utf-8")) <= 2000


def test_invalid_utf8_does_not_break_the_run(tmp_path: Path) -> None:
    path = tmp_path / "bad.log"
    path.write_bytes(b"ok line one\nbad \xff\xfe bytes here\nok line two\n")
    native_result = logfold.analyze(str(path), format="plain", engine="native", strategy="sequential")
    assert native_result.run.records == 3


def test_engines_have_default_masks_in_sync() -> None:
    native_masks = _core.default_masks()
    assert [(m["name"], m["pattern"], m["token"], m["ascii"]) for m in native_masks] == [
        (m.name, m.pattern, m.token, m.ascii) for m in DEFAULT_MASKS
    ]


def test_execution_config_object_is_honoured(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app", execution=ExecutionConfig(engine="python"))
    assert result.metrics.engine == "python"
