"""The ``logfold plugins`` commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.ext import registry
from logfold.plugins import catalog

runner = CliRunner()


class Pairing:
    name = "pairing"

    def match(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def plugin(name: str, package: str, **changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "kinds": ["format"],
        "package": package,
        "specifier": ">=1",
        "description": f"{name} plugin",
    }
    base.update(changes)
    return base


@pytest.fixture
def catalog_file(tmp_path: Path) -> str:
    path = tmp_path / "catalog.json"
    document = {
        "schema_version": 1,
        "plugins": [plugin("haproxy", "logfold-haproxy"), plugin("pytest-plugin", "pytest", kinds=["reporter"])],
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return str(path)


def test_list_shows_built_in_plugins() -> None:
    result = runner.invoke(app, ["plugins", "list"])
    assert result.exit_code == 0
    for name in ("logfmt", "serilog-clef", "markdown", "csv", "jaccard", "nginx", "html"):
        assert name in result.stdout
    assert "built-in" in result.stdout


def test_list_json() -> None:
    rows = json.loads(runner.invoke(app, ["plugins", "list", "--json"]).stdout)
    jaccard = next(row for row in rows if row["kind"] == "matcher" and row["name"] == "jaccard")
    assert jaccard["source"] == "built-in"
    assert jaccard["status"] == "built-in"
    assert set(jaccard) == {
        "kind",
        "name",
        "status",
        "source",
        "package",
        "version",
        "description",
        "requirement",
        "install",
        "homepage",
        "min_logfold",
        "compatible",
    }


def test_check_with_the_bundled_catalog_is_offline_and_has_nothing_new(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: pytest.fail("network used"))
    result = runner.invoke(app, ["plugins", "check"])
    assert result.exit_code == 0
    assert "bundled" in result.stdout
    assert "No new plugins" in result.stdout


def test_check_lists_only_plugins_that_are_not_installed(catalog_file: str) -> None:
    result = runner.invoke(app, ["plugins", "check", "--catalog", catalog_file])
    assert result.exit_code == 0
    assert "haproxy" in result.stdout
    assert "pytest-plugin" not in result.stdout
    assert "logfold plugins install NAME" in result.stdout


def test_check_json(catalog_file: str) -> None:
    payload = json.loads(runner.invoke(app, ["plugins", "check", "--catalog", catalog_file, "--json"]).stdout)
    assert payload["catalog"] == catalog_file
    assert [p["name"] for p in payload["new"]] == ["haproxy"]
    assert payload["new"][0]["requirement"] == "logfold-haproxy>=1"


def test_check_online_is_blocked_by_the_offline_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(catalog.ENV_OFFLINE, "1")
    result = runner.invoke(app, ["plugins", "check", "--online"])
    assert result.exit_code == exit_codes.ERROR
    assert catalog.ENV_OFFLINE in result.output


def test_a_broken_catalog_is_a_clean_error(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"schema_version": 1, "plugins": [plugin("x", "--pre")]}), encoding="utf-8")
    result = runner.invoke(app, ["plugins", "check", "--catalog", str(path)])
    assert result.exit_code == exit_codes.ERROR
    assert "invalid plugin catalog" in result.output


def test_install_asks_for_confirmation_and_runs_pip(catalog_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[str] = []
    monkeypatch.setattr(catalog, "install", lambda entry: installed.append(entry.requirement) or 0)
    result = runner.invoke(app, ["plugins", "install", "haproxy", "--catalog", catalog_file], input="y\n")
    assert result.exit_code == 0, result.output
    assert installed == ["logfold-haproxy>=1"]
    assert "logfold-haproxy>=1" in result.stdout
    assert "Installed" in result.stdout


def test_install_declined_does_nothing(catalog_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "install", lambda _entry: pytest.fail("pip must not run"))
    result = runner.invoke(app, ["plugins", "install", "haproxy", "--catalog", catalog_file], input="n\n")
    assert result.exit_code == exit_codes.ERROR
    assert "cancelled" in result.output


def test_install_yes_skips_the_question(catalog_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(catalog, "install", lambda entry: calls.append(entry.name) or 0)
    result = runner.invoke(app, ["plugins", "install", "haproxy", "--yes", "--catalog", catalog_file])
    assert result.exit_code == 0
    assert calls == ["haproxy"]


def test_install_only_accepts_names_from_the_catalog(catalog_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "install", lambda _entry: pytest.fail("pip must not run"))
    for name in ("evil-package", "https://evil.example/x.whl", "logfold-haproxy>=1"):
        result = runner.invoke(app, ["plugins", "install", name, "--yes", "--catalog", catalog_file])
        assert result.exit_code == exit_codes.ERROR
        assert "unknown plugin" in result.output


def test_install_skips_a_package_that_is_already_installed(catalog_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "install", lambda _entry: pytest.fail("pip must not run"))
    result = runner.invoke(app, ["plugins", "install", "pytest-plugin", "--yes", "--catalog", catalog_file])
    assert result.exit_code == 0
    assert "already installed" in result.stdout


def test_install_reports_a_pip_failure(catalog_file: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(catalog, "install", lambda _entry: 3)
    result = runner.invoke(app, ["plugins", "install", "haproxy", "--yes", "--catalog", catalog_file])
    assert result.exit_code == exit_codes.ERROR
    assert "exit code 3" in result.output


def test_remote_descriptions_cannot_inject_terminal_markup(tmp_path: Path) -> None:
    path = tmp_path / "markup.json"
    document = {"schema_version": 1, "plugins": [plugin("fancy", "logfold-fancy", description="[bold red]loud[/]")]}
    path.write_text(json.dumps(document), encoding="utf-8")
    result = runner.invoke(app, ["plugins", "check", "--catalog", str(path)])
    assert "[bold red]loud[/]" in result.stdout


def test_the_plugins_group_is_listed_in_the_help() -> None:
    result = runner.invoke(app, ["--help"])
    assert "plugins" in result.stdout
    assert runner.invoke(app, ["plugins", "--help"]).exit_code == 0


def test_list_includes_available_plugins_with_status(catalog_file: str) -> None:
    result = runner.invoke(app, ["plugins", "list", "--catalog", catalog_file])
    assert result.exit_code == 0
    line = next(line for line in result.stdout.splitlines() if "haproxy" in line)
    assert "available" in line
    assert "logfold-haproxy" in line
    assert "logfold plugins install NAME" in result.stdout


def test_list_installed_hides_available_ones(catalog_file: str) -> None:
    result = runner.invoke(app, ["plugins", "list", "--installed", "--catalog", catalog_file])
    assert result.exit_code == 0
    assert "haproxy" not in result.stdout
    assert "jaccard" in result.stdout


def test_list_available_shows_only_available_ones(catalog_file: str) -> None:
    result = runner.invoke(app, ["plugins", "list", "--available", "--catalog", catalog_file, "--json"])
    assert [(row["name"], row["status"]) for row in json.loads(result.stdout)] == [("haproxy", "available")]


def test_list_kind_filter(catalog_file: str) -> None:
    rows = json.loads(runner.invoke(app, ["plugins", "list", "--kind", "matcher", "--json"]).stdout)
    assert {row["kind"] for row in rows} == {"matcher"}


def test_list_with_an_empty_result_says_so() -> None:
    result = runner.invoke(app, ["plugins", "list", "--available"])
    assert result.exit_code == 0
    assert "No plugins match" in result.stdout


def test_list_rejects_both_status_filters_and_unknown_kind() -> None:
    both = runner.invoke(app, ["plugins", "list", "--installed", "--available"])
    assert both.exit_code == exit_codes.ERROR
    assert "exclude each other" in both.stderr
    kind = runner.invoke(app, ["plugins", "list", "--kind", "formatter"])
    assert kind.exit_code == exit_codes.ERROR
    assert "unknown plugin kind" in kind.stderr


def test_info_for_an_available_plugin_shows_how_to_install_it(catalog_file: str) -> None:
    result = runner.invoke(app, ["plugins", "info", "haproxy", "--catalog", catalog_file])
    assert result.exit_code == 0
    assert "available" in result.stdout
    assert "logfold plugins install haproxy" in result.stdout
    assert "logfold-haproxy>=1" in result.stdout


def test_info_for_a_built_in_plugin_shows_how_to_use_it() -> None:
    result = runner.invoke(app, ["plugins", "info", "jaccard"])
    assert result.exit_code == 0
    assert "built-in" in result.stdout
    assert "--matcher jaccard" in result.stdout


def test_info_json(catalog_file: str) -> None:
    rows = json.loads(runner.invoke(app, ["plugins", "info", "haproxy", "--catalog", catalog_file, "--json"]).stdout)
    assert rows[0]["install"] == "logfold plugins install haproxy"


def test_info_for_an_unknown_name_suggests_a_close_one(catalog_file: str) -> None:
    result = runner.invoke(app, ["plugins", "info", "haproxi", "--catalog", catalog_file])
    assert result.exit_code == exit_codes.ERROR
    assert "unknown plugin 'haproxi'" in result.stderr
    assert "did you mean 'haproxy'?" in result.stderr


def test_list_shows_where_a_folder_plugin_comes_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_matchers", dict(registry._matchers))
    monkeypatch.setattr(registry, "_origins", dict(registry._origins))
    registry.register_matcher(Pairing())
    registry._origins[("matcher", "pairing")] = registry.PluginOrigin("/home/me/plugins/pairing.py")
    result = runner.invoke(app, ["plugins", "list", "--kind", "matcher"], env={"COLUMNS": "200"})
    line = next(line for line in result.stdout.splitlines() if "pairing" in line)
    assert "installed" in line
    assert "/home/me/plugins/pairing.py" in line


def test_control_characters_from_package_metadata_do_not_reach_the_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(registry, "_matchers", dict(registry._matchers))
    monkeypatch.setattr(registry, "_origins", dict(registry._origins))
    monkeypatch.setattr("logfold.plugins.listing._summary", lambda _package: "evil\x1b]0;owned\x07 text")
    registry.register_matcher(Pairing())
    registry._origins[("matcher", "pairing")] = registry.PluginOrigin("evil-pkg 1", "evil-pkg", "1")
    for command in (["plugins", "list", "--kind", "matcher"], ["plugins", "info", "pairing"]):
        result = runner.invoke(app, command)
        assert "\x1b" not in result.stdout
        assert "\x07" not in result.stdout
        assert "evil" in result.stdout
