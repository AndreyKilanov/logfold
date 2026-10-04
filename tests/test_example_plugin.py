"""The example plugin under ``examples/`` must keep working with the current logfold."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

import logfold

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "examples" / "logfold-example-plugin"


@pytest.fixture(scope="module")
def plugin() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "logfold_example_plugin", PLUGIN_DIR / "logfold_example_plugin" / "__init__.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


def test_format_parses_the_sample_log(plugin: ModuleType) -> None:
    result = logfold.analyze(str(PLUGIN_DIR / "sample.log"), format=plugin.EXAMPLE, engine="python")
    assert result.run.records == 6
    assert result.run.unparsed == 0
    assert {t.text for t in result.templates} == {
        "user <NUM> logged in from <IP>",
        "slow query took <NUM> ms",
        "upstream <NUM> timed out",
    }
    assert result.templates[0].first_seen is not None


def test_markdown_reporter_renders_analysis_and_diff(plugin: ModuleType, tmp_path: Path) -> None:
    sample = str(PLUGIN_DIR / "sample.log")
    analysis = plugin.MarkdownReporter().render(logfold.analyze(sample, format=plugin.EXAMPLE, engine="python"))
    assert "| 3 | INFO | `user <NUM> logged in from <IP>` |" in analysis
    other = tmp_path / "other.log"
    other.write_text("04/Oct/2026:10:00:01.000 ERROR disk full on node 1\n", encoding="utf-8")
    comparison = logfold.diff(sample, str(other), format=plugin.EXAMPLE, engine="python", min_count=1)
    diff = plugin.MarkdownReporter().render(comparison)
    assert "## New templates" in diff
    assert "`disk full on node <NUM>`" in diff


def test_first_word_matcher_pairs_reworded_templates(plugin: ModuleType) -> None:
    matcher = plugin.FirstWordMatcher()
    pairs = matcher.match(
        ["retry failed after <NUM> attempts", "cache cleared"], ["retry gave up after <NUM> attempts"]
    )
    assert pairs == [(0, 0)]
    assert matcher.match(["a b"], ["c d"]) == []
