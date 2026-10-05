"""Plugins that users drop into their own folder, and the templates that help to write them."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

import logfold
from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.errors import ConfigError
from logfold.ext import registry
from logfold.plugins import templates

runner = CliRunner()

PLUGIN = """
from logfold.ext import RegexFormat


class Shout:
    name = "shout"
    kinds = ("analysis",)

    def render(self, result, **options):
        return "\\n".join(t.text.upper() for t in result.top(3)) + "\\n"


class FirstWord:
    name = "first-word"

    def match(self, before_only, after_only):
        pairs, used = [], set()
        for j, text in enumerate(after_only):
            for i, other in enumerate(before_only):
                if i not in used and other.split()[:1] == text.split()[:1]:
                    pairs.append((i, j))
                    used.add(i)
                    break
        return pairs


FORMATS = [
    RegexFormat(
        name="mine",
        pattern=r"^(?P<ts>\\S+) (?P<lvl>[A-Za-z]+) (?P<msg>.*)$",
        message_group="msg",
        time_group="ts",
        level_group="lvl",
    )
]
REPORTERS = [Shout]
MATCHERS = [FirstWord()]
"""

LOG = "2026-10-04T10:00:01Z WARN disk 91 percent full\n2026-10-04T10:00:02Z INFO user 7 in\n"


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An empty user config folder, and a registry that is restored after the test."""
    base = tmp_path / "config"
    base.mkdir()
    monkeypatch.setenv("APPDATA", str(base))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base))
    monkeypatch.delenv(registry.ENV_NO_USER_PLUGINS, raising=False)
    monkeypatch.delenv(registry.ENV_PLUGIN_PATH, raising=False)
    for attribute in ("_formats", "_reporters", "_matchers", "_origins"):
        monkeypatch.setattr(registry, attribute, dict(getattr(registry, attribute)))
    monkeypatch.setattr(registry, "_explicit_dirs", [])
    monkeypatch.setattr(registry, "_plugins_loaded", False)
    yield base
    for name in [m for m in sys.modules if m.startswith("logfold_user_plugin_")]:
        del sys.modules[name]


@pytest.fixture
def plugin_dir(home: Path) -> Path:
    folder = registry.default_plugin_dir()
    folder.mkdir(parents=True)
    return folder


def write(folder: Path, name: str, text: str) -> Path:
    path = folder / name
    path.write_text(text, encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o644)
    return path


def test_default_folder_is_in_the_user_config(home: Path) -> None:
    folder = registry.default_plugin_dir()
    assert folder == home / "logfold" / "plugins"


def test_search_folders_follow_the_environment(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    extra = tmp_path / "extra"
    other = tmp_path / "other"
    monkeypatch.setenv(registry.ENV_PLUGIN_PATH, os.pathsep.join([str(extra), str(other), str(extra)]))
    assert registry.plugin_directories() == [registry.default_plugin_dir(), extra, other]
    assert Path.cwd() not in registry.plugin_directories()
    monkeypatch.setenv(registry.ENV_NO_USER_PLUGINS, "1")
    assert registry.plugin_directories() == []
    monkeypatch.setenv(registry.ENV_NO_USER_PLUGINS, "0")
    assert registry.plugin_directories()


def test_a_dropped_file_provides_a_format_a_reporter_and_a_matcher(plugin_dir: Path, tmp_path: Path) -> None:
    path = write(plugin_dir, "mine.py", PLUGIN)
    log = tmp_path / "a.log"
    log.write_text(LOG, encoding="utf-8")

    result = logfold.analyze(str(log), format="mine", engine="python")
    assert {t.text: t.level for t in result.templates} == {"disk <NUM> percent full": "WARN", "user <NUM> in": "INFO"}
    assert result.render("shout").splitlines()[0] in {"DISK <NUM> PERCENT FULL", "USER <NUM> IN"}
    assert registry.get_matcher("first-word").name == "first-word"
    sources = {(kind, name): source for kind, name, source in registry.plugin_sources()}
    assert sources[("format", "mine")] == str(path)
    assert sources[("reporter", "shout")] == str(path)
    assert sources[("matcher", "first-word")] == str(path)


def test_a_matcher_from_the_folder_is_used_by_diff(plugin_dir: Path, tmp_path: Path) -> None:
    write(plugin_dir, "mine.py", PLUGIN)
    before = tmp_path / "b.log"
    after = tmp_path / "a.log"
    before.write_text("2026-10-04T10:00:01Z ERROR retry failed after 3 tries\n", encoding="utf-8")
    after.write_text("2026-10-04T10:00:01Z ERROR retry gave up after 3 tries\n", encoding="utf-8")
    options = {"format": "mine", "engine": "python", "min_count": 1}
    assert len(logfold.diff(str(before), str(after), **options).new_templates) == 1
    assert len(logfold.diff(str(before), str(after), matcher="first-word", **options).new_templates) == 0


def test_a_package_folder_with_relative_imports_loads(plugin_dir: Path) -> None:
    package = plugin_dir / "pack"
    package.mkdir()
    write(package, "helper.py", 'PATTERN = r"^(?P<msg>.*)$"\n')
    write(
        package,
        "__init__.py",
        "from logfold.ext import RegexFormat\nfrom .helper import PATTERN\n"
        'FORMATS = [RegexFormat(name="packed", pattern=PATTERN, message_group="msg")]\n',
    )
    assert "packed" in registry.format_names()


def test_private_hidden_and_non_python_files_are_ignored(plugin_dir: Path) -> None:
    for name in ("_private.py", ".hidden.py", "notes.txt", "data.json"):
        write(plugin_dir, name, 'raise RuntimeError("must not be imported")\n')
    (plugin_dir / "empty").mkdir()
    registry.load_plugins(force=True)
    assert "plain" in registry.format_names()


def test_a_broken_file_is_skipped_and_the_others_still_load(plugin_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    write(plugin_dir, "a_broken.py", "this is not python\n")
    write(plugin_dir, "b_raises.py", 'raise RuntimeError("boom")\n')
    write(plugin_dir, "c_good.py", PLUGIN)
    with caplog.at_level(logging.WARNING, logger="logfold"):
        registry.load_plugins(force=True)
    assert "mine" in registry.format_names()
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "a_broken.py" in messages
    assert "b_raises.py" in messages


def test_invalid_items_are_skipped_with_a_warning(plugin_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    write(
        plugin_dir,
        "bad.py",
        "class NoRender:\n    name = 'no-render'\n    kinds = ('analysis',)\n"
        "class NoMatch:\n    name = 'no-match'\n"
        "REPORTERS = [NoRender]\nMATCHERS = [NoMatch]\nFORMATS = 'not a list'\n",
    )
    with caplog.at_level(logging.WARNING, logger="logfold"):
        registry.load_plugins(force=True)
    assert "no-render" not in registry.reporter_names()
    assert "no-match" not in {name for kind, name, _ in registry.plugin_sources() if kind == "matcher"}
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "FORMATS must be a list" in messages
    assert "failed to register a reporter" in messages


def test_a_user_plugin_can_replace_a_default_name(plugin_dir: Path) -> None:
    write(plugin_dir, "mine.py", PLUGIN.replace('name="mine"', 'name="logfmt"'))
    registry.load_plugins(force=True)
    sources = {(kind, name): source for kind, name, source in registry.plugin_sources()}
    assert sources[("format", "logfmt")].endswith("mine.py")


def test_explicit_folders_work_before_and_after_plugins_are_loaded(home: Path, tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for folder, name in ((first, "one"), (second, "two")):
        folder.mkdir()
        write(folder, f"{name}.py", PLUGIN.replace('name="mine"', f'name="{name}"'))
    registry.add_plugin_directory(first)
    registry.load_plugins(force=True)
    assert "one" in registry.format_names()
    registry.add_plugin_directory(second)
    assert "two" in registry.format_names()


def test_an_explicit_folder_ignores_the_off_switch(home: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(registry.ENV_NO_USER_PLUGINS, "1")
    default = registry.default_plugin_dir()
    default.mkdir(parents=True)
    write(default, "mine.py", PLUGIN)
    chosen = tmp_path / "chosen"
    chosen.mkdir()
    write(chosen, "other.py", PLUGIN.replace('name="mine"', 'name="other"'))
    registry.add_plugin_directory(chosen)
    registry.load_plugins(force=True)
    names = registry.format_names()
    assert "other" in names
    assert "mine" not in names


def test_a_missing_explicit_folder_is_reported(home: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    registry.add_plugin_directory(tmp_path / "nowhere")
    with caplog.at_level(logging.WARNING, logger="logfold"):
        registry.load_plugins(force=True)
    assert any("does not exist" in record.getMessage() for record in caplog.records)


posix_only = pytest.mark.skipif(os.name != "posix", reason="permission bits are checked on POSIX only")


@posix_only
def test_a_file_that_everybody_can_write_is_not_loaded(plugin_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = write(plugin_dir, "mine.py", PLUGIN)
    path.chmod(path.stat().st_mode | stat.S_IWOTH)
    with caplog.at_level(logging.WARNING, logger="logfold"):
        registry.load_plugins(force=True)
    assert "mine" not in registry.format_names()
    assert any("other users can change" in record.getMessage() for record in caplog.records)


@posix_only
def test_a_folder_that_everybody_can_write_is_not_loaded(plugin_dir: Path, caplog: pytest.LogCaptureFixture) -> None:
    write(plugin_dir, "mine.py", PLUGIN)
    plugin_dir.chmod(0o777)
    try:
        with caplog.at_level(logging.WARNING, logger="logfold"):
            registry.load_plugins(force=True)
    finally:
        plugin_dir.chmod(0o755)
    assert "mine" not in registry.format_names()
    assert any("other users can change" in record.getMessage() for record in caplog.records)


@posix_only
def test_group_write_access_is_allowed(plugin_dir: Path) -> None:
    path = write(plugin_dir, "mine.py", PLUGIN)
    path.chmod(0o664)
    registry.load_plugins(force=True)
    assert "mine" in registry.format_names()


@pytest.mark.parametrize("kind", templates.KINDS)
def test_every_template_loads_and_is_usable(plugin_dir: Path, kind: str, tmp_path: Path) -> None:
    write(plugin_dir, "my_thing.py", templates.render_template(kind, "my-thing"))
    registry.load_plugins(force=True)
    log = tmp_path / "a.log"
    log.write_text(LOG, encoding="utf-8")
    if kind == "format":
        result = logfold.analyze(str(log), format="my-thing", engine="python")
        assert result.run.records == 2
    elif kind == "reporter":
        result = logfold.analyze(str(log), format="plain", engine="python")
        assert "disk" in result.render("my-thing")
        comparison = logfold.diff(str(log), str(log), format="plain", engine="python")
        assert comparison.render("my-thing").startswith("0 new")
    else:
        assert registry.get_matcher("my-thing").match(["retry failed"], ["retry gave up"]) == [(0, 0)]


@pytest.mark.parametrize(
    ("kind", "name"), [("parser", "x"), ("format", "1bad"), ("format", "has space"), ("format", "")]
)
def test_templates_reject_bad_kinds_and_names(kind: str, name: str) -> None:
    with pytest.raises(ConfigError):
        templates.render_template(kind, name)


def test_cli_dir_and_new_write_into_the_plugin_folder(home: Path) -> None:
    shown = runner.invoke(app, ["plugins", "dir"])
    assert shown.exit_code == 0
    assert "does not exist yet" in shown.stdout
    created = runner.invoke(app, ["plugins", "new", "format", "my-fmt"])
    assert created.exit_code == 0, created.output
    target = registry.default_plugin_dir() / "my_fmt.py"
    assert target.is_file()
    assert "exists" in runner.invoke(app, ["plugins", "dir"]).stdout
    again = runner.invoke(app, ["plugins", "new", "format", "my-fmt"])
    assert again.exit_code == exit_codes.ERROR
    assert "already exists" in again.output
    assert runner.invoke(app, ["plugins", "new", "format", "my-fmt", "--force"]).exit_code == 0


def test_cli_new_rejects_bad_input(home: Path) -> None:
    for arguments in (["parser", "x"], ["format", "../escape"], ["format", "a b"]):
        result = runner.invoke(app, ["plugins", "new", *arguments])
        assert result.exit_code == exit_codes.ERROR
    assert not registry.default_plugin_dir().exists()


def test_cli_new_in_a_chosen_folder_and_plugins_dir_option(home: Path, tmp_path: Path) -> None:
    chosen = tmp_path / "mine"
    created = runner.invoke(app, ["plugins", "new", "matcher", "pairing", "--dir", str(chosen)])
    assert created.exit_code == 0, created.output
    assert "--plugins-dir" in created.stdout
    assert (chosen / "pairing.py").is_file()
    listed = runner.invoke(app, ["--plugins-dir", str(chosen), "plugins", "list", "--json"])
    rows = json.loads(listed.stdout)
    assert {"kind": "matcher", "name": "pairing", "source": str(chosen / "pairing.py")} in rows


def test_the_off_switch_is_reported_by_the_dir_command(home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(registry.ENV_NO_USER_PLUGINS, "1")
    assert "switched off" in runner.invoke(app, ["plugins", "dir"]).stdout


def test_the_example_in_the_plugins_guide_works(plugin_dir: Path, tmp_path: Path) -> None:
    guide = (Path(__file__).resolve().parents[2] / "docs" / "plugins.md").read_text(encoding="utf-8")
    section = guide[guide.index("## Your own plugins in a folder") :]
    code = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    assert code is not None
    write(plugin_dir, "from_the_guide.py", code.group(1))
    log = tmp_path / "a.log"
    log.write_text(LOG, encoding="utf-8")
    result = logfold.analyze(str(log), format="mine", engine="python")
    assert result.run.records == 2
    assert result.render("shout").strip()
