"""Plugin names in the command line: hints for unknown names, the formats listing and the option help."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from logfold.cli import exit_codes
from logfold.cli.app import app
from logfold.errors import ConfigError
from logfold.plugins import catalog

runner = CliRunner(env={"COLUMNS": "200"})


def entry(name: str, **changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "kinds": ["format"],
        "package": f"logfold-{name}",
        "specifier": ">=1",
        "description": f"{name} logs",
    }
    base.update(changes)
    return base


def squeezed(text: str) -> str:
    return " ".join(text.split())


@pytest.fixture
def bundled(monkeypatch: pytest.MonkeyPatch) -> catalog.Catalog:
    """Make the catalog that ships with logfold hold a few test plugins."""
    document = {
        "schema_version": 1,
        "plugins": [
            entry("traefik"),
            entry("newer", min_logfold="99.0.0"),
            entry("shipper", kinds=["reporter"]),
            entry("pairing", kinds=["matcher"]),
        ],
    }
    loaded = catalog.parse_catalog(document, "bundled")
    monkeypatch.setattr(catalog, "load_bundled", lambda: loaded)
    return loaded


@pytest.fixture
def log_file(tmp_path: Path) -> Path:
    path = tmp_path / "a.log"
    path.write_text("2026-10-04T10:00:01Z INFO started\n", encoding="utf-8")
    return path


def test_unknown_format_names_the_install_command(bundled: catalog.Catalog, log_file: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file), "-f", "traefik"])
    assert result.exit_code == exit_codes.ERROR
    assert "hint:" in result.stderr
    assert "the plugin 'traefik' is available: logfold plugins install traefik" in squeezed(result.stderr)
    assert "logfold formats" in result.stderr


def test_unknown_reporter_and_matcher_use_their_own_kind(bundled: catalog.Catalog, log_file: Path) -> None:
    reporter = runner.invoke(app, ["analyze", str(log_file), "--report", "shipper"])
    assert "logfold plugins install shipper" in squeezed(reporter.stderr)
    matcher = runner.invoke(app, ["diff", str(log_file), str(log_file), "--matcher", "pairing"])
    assert "logfold plugins install pairing" in squeezed(matcher.stderr)
    wrong_kind = runner.invoke(app, ["diff", str(log_file), str(log_file), "--matcher", "traefik"])
    assert "logfold plugins install" not in wrong_kind.stderr


def test_a_typo_of_an_available_name_suggests_it(bundled: catalog.Catalog, log_file: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file), "-f", "traefic"])
    assert "did you mean 'traefik'?" in result.stderr
    assert "logfold plugins install traefik" in squeezed(result.stderr)


def test_an_incompatible_plugin_is_not_offered_for_install(bundled: catalog.Catalog, log_file: Path) -> None:
    result = runner.invoke(app, ["analyze", str(log_file), "-f", "newer"])
    assert "needs logfold 99.0.0 or newer" in squeezed(result.stderr)
    assert "logfold plugins install newer" not in result.stderr


def test_a_broken_catalog_does_not_hide_the_original_error(monkeypatch: pytest.MonkeyPatch, log_file: Path) -> None:
    def broken() -> catalog.Catalog:
        raise ConfigError("invalid plugin catalog")

    monkeypatch.setattr(catalog, "load_bundled", broken)
    result = runner.invoke(app, ["analyze", str(log_file), "-f", "nginxx"])
    assert result.exit_code == exit_codes.ERROR
    assert "unknown format 'nginxx'" in result.stderr
    assert "did you mean 'nginx'?" in result.stderr


def test_formats_lists_available_plugins_and_what_is_installed(bundled: catalog.Catalog) -> None:
    result = runner.invoke(app, ["formats"])
    assert result.exit_code == 0
    assert "nginx" in result.stdout
    assert "Available from the plugin catalog" in result.stdout
    line = next(line for line in result.stdout.splitlines() if "traefik" in line)
    assert "logfold plugins install traefik" in line
    newer = next(line for line in result.stdout.splitlines() if line.lstrip().startswith("newer"))
    assert "needs logfold 99.0.0 or newer" in newer
    assert "shipper" not in result.stdout


def test_formats_is_unchanged_when_the_catalog_has_nothing_to_offer() -> None:
    result = runner.invoke(app, ["formats"])
    assert result.exit_code == 0
    assert "Available from the plugin catalog" not in result.stdout


def test_formats_survives_a_broken_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> catalog.Catalog:
        raise ConfigError("invalid plugin catalog")

    monkeypatch.setattr(catalog, "load_bundled", broken)
    result = runner.invoke(app, ["formats"])
    assert result.exit_code == 0
    assert "nginx" in result.stdout


def test_help_names_the_available_plugins_of_the_right_kind(bundled: catalog.Catalog) -> None:
    for command in (["analyze", "--help"], ["diff", "--help"], ["inspect", "--help"]):
        result = runner.invoke(app, command)
        assert result.exit_code == 0
        assert "Available to install: traefik" in squeezed(result.stdout)
    diff_help = squeezed(runner.invoke(app, ["diff", "--help"]).stdout)
    assert "Available to install: shipper" in diff_help
    assert "Available to install: pairing" in diff_help
    assert "Available to install: pairing" not in squeezed(runner.invoke(app, ["analyze", "--help"]).stdout)


def test_help_does_not_repeat_the_text_when_shown_twice(bundled: catalog.Catalog) -> None:
    first = squeezed(runner.invoke(app, ["analyze", "--help"]).stdout)
    second = squeezed(runner.invoke(app, ["analyze", "--help"]).stdout)
    assert second.count("Available to install:") == first.count("Available to install:")


def test_help_is_unchanged_without_catalog_plugins() -> None:
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "Available to install" not in result.stdout


def test_a_normal_run_never_reads_the_catalog(monkeypatch: pytest.MonkeyPatch, log_file: Path) -> None:
    monkeypatch.setattr(catalog, "load_bundled", lambda: pytest.fail("the catalog was read"))
    result = runner.invoke(app, ["analyze", str(log_file), "--json"])
    assert result.exit_code == 0


def test_list_and_info_mark_an_incompatible_plugin(bundled: catalog.Catalog) -> None:
    listed = runner.invoke(app, ["plugins", "list", "--available"])
    assert "needs logfold 99.0.0" in next(line for line in listed.stdout.splitlines() if "newer" in line)
    info = runner.invoke(app, ["plugins", "info", "newer"])
    assert "needs:    logfold 99.0.0 or newer" in info.stdout
    assert "cannot be installed" in info.stdout
    assert "install:" not in info.stdout
    rows = json.loads(runner.invoke(app, ["plugins", "info", "newer", "--json"]).stdout)
    assert (rows[0]["compatible"], rows[0]["min_logfold"]) == (False, "99.0.0")


def test_install_refuses_an_incompatible_plugin_before_asking(bundled: catalog.Catalog) -> None:
    result = runner.invoke(app, ["plugins", "install", "newer"])
    assert result.exit_code == exit_codes.ERROR
    assert "needs logfold 99.0.0 or newer" in result.stderr
    assert "hint: upgrade logfold" in result.stderr
    assert "Install it?" not in result.stdout


def test_check_json_has_the_compatibility_fields(bundled: catalog.Catalog) -> None:
    payload = json.loads(runner.invoke(app, ["plugins", "check", "--json"]).stdout)
    by_name = {plugin["name"]: plugin for plugin in payload["new"]}
    assert (by_name["newer"]["compatible"], by_name["newer"]["min_logfold"]) == (False, "99.0.0")
    assert by_name["traefik"]["compatible"] is True


def test_new_reports_an_existing_file_with_a_hint(tmp_path: Path) -> None:
    runner.invoke(app, ["plugins", "new", "format", "mine", "--dir", str(tmp_path)])
    again = runner.invoke(app, ["plugins", "new", "format", "mine", "--dir", str(tmp_path)])
    assert again.exit_code == exit_codes.ERROR
    assert "already exists" in again.stderr
    assert "--force" in again.stderr
