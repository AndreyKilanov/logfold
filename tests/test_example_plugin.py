"""The example plugins under ``examples/`` must keep working with the current logfold."""

from __future__ import annotations

import csv
import importlib
import io
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

import logfold
from conftest import requires_native
from logfold.ext import DiffMatcher, Reporter, registry

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "examples" / "logfold-example-plugin"
SAMPLES = PLUGIN_DIR / "samples"


@pytest.fixture(scope="module")
def plugin() -> Iterator[ModuleType]:
    sys.path.insert(0, str(PLUGIN_DIR))
    try:
        yield importlib.import_module("logfold_example_plugin")
    finally:
        sys.path.remove(str(PLUGIN_DIR))
        for name in [m for m in sys.modules if m.split(".")[0] == "logfold_example_plugin"]:
            del sys.modules[name]


def _templates(result: logfold.AnalysisResult) -> dict[str, tuple[int, str | None]]:
    return {t.text: (t.count, t.level) for t in result.templates}


def test_every_entry_point_of_the_example_resolves(plugin: ModuleType) -> None:
    text = (PLUGIN_DIR / "pyproject.toml").read_text(encoding="utf-8")
    groups = set(re.findall(r'^\[project\.entry-points\."([\w.]+)"\]$', text, re.MULTILINE))
    assert groups == {"logfold.formats", "logfold.reporters", "logfold.matchers"}
    targets = re.findall(r'^[\w-]+ = "([\w.]+):(\w+)"$', text, re.MULTILINE)
    assert len(targets) == 7
    for module, attribute in targets:
        assert module == "logfold_example_plugin"
        assert hasattr(plugin, attribute), attribute


def test_logfmt_format(plugin: ModuleType) -> None:
    result = logfold.analyze(str(SAMPLES / "app.logfmt"), format=plugin.LOGFMT, engine="python")
    assert result.run.unparsed == 0
    assert _templates(result) == {
        'msg="user <NUM> logged in" ip=<IP>': (3, "INFO"),
        'msg="slow query" <*>': (2, "WARN"),
        'msg="upstream timed out" id=<NUM>': (1, "ERROR"),
    }
    assert result.templates[0].first_seen is not None


def test_serilog_clef_format(plugin: ModuleType) -> None:
    result = logfold.analyze(str(SAMPLES / "serilog.jsonl"), format=plugin.SERILOG_CLEF, engine="python")
    assert _templates(result) == {
        "Cache warmed <NUM> keys": (2, None),
        "Payment <NUM> failed": (1, "ERROR"),
        "User <NUM> logged in": (1, "WARN"),
    }


def test_ci_blocks_format_joins_continuation_lines(plugin: ModuleType) -> None:
    result = logfold.analyze(str(SAMPLES / "ci.log"), format=plugin.CI_BLOCKS, engine="python")
    assert result.run.records == 3
    assert "=== job test started running <NUM> tests FAILED test_login" in _templates(result)


@requires_native
@pytest.mark.parametrize(
    ("name", "sample"),
    [("LOGFMT", "app.logfmt"), ("SERILOG_CLEF", "serilog.jsonl"), ("CI_BLOCKS", "ci.log")],
)
def test_native_and_python_engines_agree_on_the_example_formats(plugin: ModuleType, name: str, sample: str) -> None:
    spec = getattr(plugin, name)
    native = logfold.analyze(str(SAMPLES / sample), format=spec, engine="native")
    reference = logfold.analyze(str(SAMPLES / sample), format=spec, engine="python")
    assert [(t.text, t.count, t.level) for t in native.templates] == [
        (t.text, t.count, t.level) for t in reference.templates
    ]


def test_reporters_render_analysis_and_diff(plugin: ModuleType) -> None:
    analysis = logfold.analyze(str(SAMPLES / "app.logfmt"), format=plugin.LOGFMT, engine="python")
    markdown = plugin.MarkdownReporter().render(analysis)
    assert '| 3 | INFO | `msg="user <NUM> logged in" ip=<IP>` |' in markdown
    rows = list(csv.reader(io.StringIO(plugin.CsvReporter().render(analysis))))
    assert rows[0] == ["count", "level", "first_seen", "last_seen", "template"]
    assert rows[1][:2] == ["3", "INFO"]
    assert len(rows) == 4
    assert len(list(csv.reader(io.StringIO(plugin.CsvReporter().render(analysis, top=1))))) == 2
    comparison = logfold.diff(
        str(SAMPLES / "before.logfmt"),
        str(SAMPLES / "after.logfmt"),
        format=plugin.LOGFMT,
        engine="python",
        min_count=1,
    )
    assert "## New templates" in plugin.MarkdownReporter().render(comparison)
    kinds = [row[0] for row in csv.reader(io.StringIO(plugin.CsvReporter().render(comparison)))][1:]
    assert kinds == ["new", "disappeared"]


def test_reporters_and_matchers_follow_the_protocols(plugin: ModuleType) -> None:
    for reporter in (plugin.MarkdownReporter(), plugin.CsvReporter()):
        assert isinstance(reporter, Reporter)
    for matcher in (plugin.FirstWordMatcher(), plugin.JaccardMatcher()):
        assert isinstance(matcher, DiffMatcher)


def test_matchers_pair_reworded_templates(plugin: ModuleType) -> None:
    before = ['msg="retry failed after <NUM> attempts" id=<NUM>', "cache cleared"]
    after = ['msg="retry gave up after <NUM> attempts" id=<NUM>']
    assert plugin.JaccardMatcher().match(before, after) == [(0, 0)]
    assert plugin.JaccardMatcher().match(["a b c"], ["x y z"]) == []
    assert plugin.FirstWordMatcher().match(["retry failed", "other"], ["retry gave up"]) == [(0, 0)]
    assert plugin.FirstWordMatcher().match(["a b"], ["c d"]) == []


@pytest.mark.parametrize("matcher", ["example-first-word", "example-jaccard"])
def test_matcher_changes_the_diff_result(plugin: ModuleType, monkeypatch: pytest.MonkeyPatch, matcher: str) -> None:
    monkeypatch.setattr(registry, "_matchers", dict(registry._matchers))
    registry.register_matcher(plugin.FirstWordMatcher())
    registry.register_matcher(plugin.JaccardMatcher())
    arguments = (str(SAMPLES / "before.logfmt"), str(SAMPLES / "after.logfmt"))
    options = {"format": plugin.LOGFMT, "engine": "python", "min_count": 1}
    exact = logfold.diff(*arguments, **options)
    assert (len(exact.new_templates), len(exact.disappeared)) == (1, 1)
    paired = logfold.diff(*arguments, matcher=matcher, **options)
    assert (len(paired.new_templates), len(paired.disappeared)) == (0, 0)
