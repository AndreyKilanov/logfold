"""Catalog compatibility (min_logfold), hints for unknown names and writing plugin templates."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from logfold.errors import ConfigError, SourceError
from logfold.plugins import catalog, list_plugins, plugin_info, unknown_name_hint, write_template


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


@pytest.fixture
def test_catalog() -> catalog.Catalog:
    document = {
        "schema_version": 1,
        "plugins": [
            entry("haproxy", min_logfold="0.1.0"),
            entry("newer", min_logfold="99.0.0"),
            entry("shipper", kinds=["reporter"]),
        ],
    }
    return catalog.parse_catalog(document, "test-catalog")


@pytest.mark.parametrize("value", ["1.2", "v1.2.3", "1.2.3.4", "1.2.x", "", "-1.0.0", "1.2.3; rm"])
def test_min_logfold_must_look_like_a_version(value: str) -> None:
    document = {"schema_version": 1, "plugins": [entry("a", min_logfold=value)]}
    with pytest.raises(ConfigError, match="min_logfold"):
        catalog.parse_catalog(document, "test")


def test_min_logfold_is_optional_and_kept() -> None:
    parsed = catalog.parse_catalog({"schema_version": 1, "plugins": [entry("a"), entry("b", min_logfold="0.4.0")]}, "t")
    assert [e.min_logfold for e in parsed.entries] == [None, "0.4.0"]


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("0.4.0", True),
        ("0.4.1", True),
        ("0.10.0", True),
        ("1.0.0", True),
        ("0.3.9", False),
        ("0.4.0.dev1", True),
        ("0.3.0rc1", False),
        ("0+unknown", True),
        ("garbage", True),
    ],
)
def test_fits_compares_versions_as_numbers(version: str, expected: bool) -> None:
    plugin = catalog.parse_catalog({"schema_version": 1, "plugins": [entry("a", min_logfold="0.4.0")]}, "t").entries[0]
    assert plugin.fits(version) is expected


def test_a_plugin_without_a_minimum_always_fits(test_catalog: catalog.Catalog) -> None:
    assert test_catalog.find("shipper") is not None
    assert test_catalog.find("shipper").fits("0.0.1")  # type: ignore[union-attr]


def test_require_compatible_raises_with_a_hint(test_catalog: catalog.Catalog) -> None:
    newer = test_catalog.find("newer")
    assert newer is not None
    with pytest.raises(ConfigError, match=r"needs logfold 99\.0\.0 or newer") as caught:
        catalog.require_compatible(newer, "0.4.0")
    assert caught.value.hint is not None
    assert "upgrade" in caught.value.hint


def test_install_refuses_an_incompatible_plugin_without_running_anything(test_catalog: catalog.Catalog) -> None:
    newer = test_catalog.find("newer")
    assert newer is not None
    with pytest.raises(ConfigError, match="needs logfold"):
        catalog.install(newer, runner=lambda *_a, **_k: pytest.fail("the installer must not run"))


def test_listing_marks_an_incompatible_plugin(test_catalog: catalog.Catalog) -> None:
    rows = {row.name: row for row in list_plugins(status="available", catalog=test_catalog)}
    assert (rows["newer"].compatible, rows["newer"].min_logfold) == (False, "99.0.0")
    assert (rows["haproxy"].compatible, rows["haproxy"].min_logfold) == (True, "0.1.0")
    assert plugin_info("shipper", catalog=test_catalog)[0].min_logfold is None


def test_hint_offers_the_install_command_for_an_exact_catalog_name(test_catalog: catalog.Catalog) -> None:
    hint = unknown_name_hint("format", "haproxy", test_catalog)
    assert hint == "the plugin 'haproxy' is available: logfold plugins install haproxy"


def test_hint_for_an_incompatible_plugin_says_what_it_needs(test_catalog: catalog.Catalog) -> None:
    assert unknown_name_hint("format", "newer", test_catalog) == "the plugin 'newer' needs logfold 99.0.0 or newer"


def test_hint_looks_only_at_the_kind_that_was_asked_for(test_catalog: catalog.Catalog) -> None:
    assert unknown_name_hint("matcher", "haproxy", test_catalog) is None
    assert unknown_name_hint("reporter", "shipper", test_catalog) is not None


def test_hint_corrects_a_typo_among_catalog_and_installed_names(test_catalog: catalog.Catalog) -> None:
    assert unknown_name_hint("format", "haproxi", test_catalog) == (
        "did you mean 'haproxy'? the plugin 'haproxy' is available: logfold plugins install haproxy"
    )
    assert unknown_name_hint("matcher", "jacard", test_catalog) == "did you mean 'jaccard'?"


def test_hint_is_none_when_nothing_looks_alike(test_catalog: catalog.Catalog) -> None:
    assert unknown_name_hint("format", "zzzzzz", test_catalog) is None


def test_hint_never_raises_when_the_catalog_is_broken(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken() -> catalog.Catalog:
        raise ConfigError("invalid plugin catalog")

    monkeypatch.setattr(catalog, "load_bundled", broken)
    assert unknown_name_hint("format", "anything") is None


def test_write_template_creates_the_folder_and_returns_the_path(tmp_path: Path) -> None:
    target = write_template("matcher", "pairing", tmp_path / "plugins")
    assert target == tmp_path / "plugins" / "pairing.py"
    assert "pairing" in target.read_text(encoding="utf-8")


def test_write_template_uses_the_user_plugin_folder_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APPDATA", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    target = write_template("format", "mine")
    assert target.parent == tmp_path / "logfold" / "plugins"


def test_write_template_does_not_overwrite_without_force(tmp_path: Path) -> None:
    first = write_template("format", "mine", tmp_path)
    first.write_text("edited", encoding="utf-8")
    with pytest.raises(ConfigError, match="already exists") as caught:
        write_template("format", "mine", tmp_path)
    assert caught.value.hint is not None
    assert first.read_text(encoding="utf-8") == "edited"
    write_template("format", "mine", tmp_path, force=True)
    assert first.read_text(encoding="utf-8") != "edited"


def test_write_template_rejects_a_bad_kind_or_name_and_writes_nothing(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        write_template("formatter", "mine", tmp_path)
    with pytest.raises(ConfigError):
        write_template("format", "../evil", tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_write_template_reports_an_unwritable_folder_as_a_source_error(tmp_path: Path) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    with pytest.raises(SourceError, match="cannot write"):
        write_template("format", "mine", blocker / "inside")
