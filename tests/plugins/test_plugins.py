"""A third-party plugin package must be discoverable through entry points without touching logfold."""

from __future__ import annotations

import sys
import textwrap
from collections.abc import Iterator
from pathlib import Path

import pytest

import logfold
from logfold.ext import registry
from logfold.ext.formats import RegexFormat

PLUGIN_MODULE = """
from logfold.ext import RegexFormat

HAPROXY = RegexFormat(
    name="traefik",
    pattern=r"^(?P<ts>\\d{2}/\\w{3}/\\d{4}:[\\d:.]+) (?P<lvl>\\w+) (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    ts_format="%d/%b/%Y:%H:%M:%S.%f",
)


class Shout:
    name = "shout"
    kinds = ("analysis",)

    def render(self, result, **options):
        return "\\n".join(t.text.upper() for t in result.top(5)) + "\\n"


class FirstWordMatcher:
    name = "first_word"

    def match(self, before_only, after_only):
        pairs = []
        used = set()
        for j, text in enumerate(after_only):
            for i, other in enumerate(before_only):
                if i not in used and other.split()[:1] == text.split()[:1]:
                    pairs.append((i, j))
                    used.add(i)
                    break
        return pairs


def make_format():
    return HAPROXY
"""

ENTRY_POINTS = """
[logfold.formats]
traefik = logfold_sample_plugin:HAPROXY
factory-traefik = logfold_sample_plugin:make_format

[logfold.reporters]
shout = logfold_sample_plugin:Shout

[logfold.matchers]
first_word = logfold_sample_plugin:FirstWordMatcher
"""


@pytest.fixture
def installed_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    (tmp_path / "logfold_sample_plugin.py").write_text(textwrap.dedent(PLUGIN_MODULE), encoding="utf-8")
    dist = tmp_path / "logfold_sample_plugin-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: logfold-sample-plugin\nVersion: 0.1\n", encoding="utf-8"
    )
    (dist / "entry_points.txt").write_text(textwrap.dedent(ENTRY_POINTS), encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(registry, "_formats", dict(registry._formats))
    monkeypatch.setattr(registry, "_reporters", dict(registry._reporters))
    monkeypatch.setattr(registry, "_matchers", dict(registry._matchers))
    registry.load_plugins(force=True)
    yield
    sys.modules.pop("logfold_sample_plugin", None)


def test_plugin_format_reporter_and_matcher_are_discovered(installed_plugin: None, tmp_path: Path) -> None:
    assert "traefik" in registry.format_names()
    assert isinstance(registry.get_format("traefik"), RegexFormat)
    assert isinstance(registry.get_format("factory-traefik"), RegexFormat)
    path = tmp_path / "ha.log"
    path.write_text(
        "04/Oct/2026:12:00:00.123 ERROR backend app1 is down\n04/Oct/2026:12:00:01.456 ERROR backend app2 is down\n",
        encoding="utf-8",
    )
    for engine in ("native", "auto"):
        result = logfold.analyze(str(path), format="traefik", engine=engine)
        assert [(t.text, t.count, t.level) for t in result.templates] == [("backend app<NUM> is down", 2, "ERROR")] or [
            (t.count, t.level) for t in result.templates
        ] == [(2, "ERROR")]
    assert result.render("shout").strip() == result.templates[0].text.upper()
    assert registry.get_matcher("first_word").name == "first_word"


def test_plugin_reporter_kind_is_enforced(installed_plugin: None, tmp_path: Path) -> None:
    before = tmp_path / "b.log"
    before.write_text("2026-10-04T12:00:00Z INFO a\n", encoding="utf-8")
    comparison = logfold.diff(str(before), str(before), format="app")
    with pytest.raises(logfold.ConfigError, match="does not support diff"):
        comparison.render("shout")


def test_plugin_matcher_is_usable_in_diff(installed_plugin: None, tmp_path: Path) -> None:
    before = tmp_path / "b.log"
    after = tmp_path / "a.log"
    before.write_text("2026-10-04T12:00:00Z INFO deploy finished in blue\n" * 3, encoding="utf-8")
    after.write_text("2026-10-04T12:00:00Z INFO deploy finished in green\n" * 3, encoding="utf-8")
    result = logfold.diff(str(before), str(after), format="app", matcher="first_word", sim_th=1.0)
    assert result.config.matcher == "first_word"


def test_broken_plugin_does_not_break_the_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dist = tmp_path / "broken_plugin-0.1.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: broken-plugin\nVersion: 0.1\n", encoding="utf-8")
    (dist / "entry_points.txt").write_text("[logfold.formats]\nbroken = no_such_module:THING\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setattr(registry, "_formats", dict(registry._formats))
    registry.load_plugins(force=True)
    assert "broken" not in registry.format_names()
    assert "plain" in registry.format_names()


def test_entry_points_are_scanned_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    real = registry.metadata.entry_points

    def counting(**selection: object) -> object:
        calls.append(selection)
        return real(**selection)

    monkeypatch.setattr(registry.metadata, "entry_points", counting)
    monkeypatch.setattr(registry, "_formats", dict(registry._formats))
    monkeypatch.setattr(registry, "_reporters", dict(registry._reporters))
    monkeypatch.setattr(registry, "_matchers", dict(registry._matchers))
    registry.load_plugins(force=True)
    assert calls == [{}]
    assert "plain" in registry.format_names()
