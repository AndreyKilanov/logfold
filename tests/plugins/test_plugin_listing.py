"""One list of built-in, installed and available plugins, and the lookup by name."""

from __future__ import annotations

from typing import Any

import pytest

from logfold.errors import ConfigError, UnknownPluginError
from logfold.ext import registry
from logfold.ext.formats import PlainFormat
from logfold.plugins import PluginInfo, catalog, closest, list_plugins, plugin_info


def entry(name: str, package: str, **changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": name,
        "kinds": ["format"],
        "package": package,
        "specifier": ">=1",
        "description": f"{name} logs",
        "homepage": f"https://example.org/{name}",
    }
    base.update(changes)
    return base


@pytest.fixture
def test_catalog() -> catalog.Catalog:
    document = {
        "schema_version": 1,
        "plugins": [
            entry("traefik", "logfold-traefik"),
            entry("sentry", "logfold-sentry", kinds=["format", "reporter"]),
            entry("from-pytest", "pytest", kinds=["reporter"]),
            entry("csv", "logfold-csv", kinds=["reporter"]),
        ],
    }
    return catalog.parse_catalog(document, "test-catalog")


@pytest.fixture
def installed_plugin(monkeypatch: pytest.MonkeyPatch) -> None:
    """A format that looks like it came from an installed package; the registry is restored afterwards."""
    registry.load_plugins()
    monkeypatch.setattr(registry, "_formats", dict(registry._formats))
    monkeypatch.setattr(registry, "_origins", dict(registry._origins))
    registry.register_format("nginx-extra", PlainFormat())
    registry._origins[("format", "nginx-extra")] = registry.PluginOrigin("pytest 2.1", "pytest", "2.1")


def by_name(rows: list[PluginInfo], kind: str, name: str) -> PluginInfo:
    return next(row for row in rows if row.kind == kind and row.name == name)


def test_built_in_plugins_come_first_and_have_no_package() -> None:
    rows = list_plugins(catalog=catalog.Catalog((), "empty"))
    assert {row.status for row in rows} == {"built-in"}
    jaccard = by_name(rows, "matcher", "jaccard")
    assert jaccard.source == "built-in"
    assert jaccard.package is None
    assert rows == sorted(rows, key=lambda row: (row.kind, row.name))


def test_the_bundled_catalog_is_the_default_and_needs_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("urllib.request.urlopen", lambda *_a, **_k: pytest.fail("network used"))
    assert list_plugins(status="available") == []


def test_catalog_plugins_that_are_not_installed_are_available(test_catalog: catalog.Catalog) -> None:
    rows = list_plugins(status="available", catalog=test_catalog)
    assert [(row.kind, row.name) for row in rows] == [
        ("format", "sentry"),
        ("format", "traefik"),
        ("reporter", "sentry"),
    ]
    traefik = rows[1]
    assert traefik.package == "logfold-traefik"
    assert traefik.version is None
    assert traefik.requirement == "logfold-traefik>=1"
    assert traefik.install == "logfold plugins install traefik"
    assert traefik.homepage == "https://example.org/traefik"
    assert traefik.source == "test-catalog"


def test_a_catalog_name_that_is_already_registered_is_not_offered_again(test_catalog: catalog.Catalog) -> None:
    rows = list_plugins(kind="reporter", catalog=test_catalog)
    assert [row.status for row in rows if row.name == "csv"] == ["built-in"]


def test_installed_plugin_has_package_version_and_catalog_description(
    installed_plugin: None, test_catalog: catalog.Catalog
) -> None:
    row = by_name(list_plugins(catalog=test_catalog), "format", "nginx-extra")
    assert (row.status, row.package, row.version) == ("installed", "pytest", "2.1")
    assert row.source == "pytest 2.1"
    assert row.description == "from-pytest logs"


def test_plugin_from_a_folder_is_installed_without_a_package(
    installed_plugin: None, test_catalog: catalog.Catalog
) -> None:
    registry._origins[("format", "nginx-extra")] = registry.PluginOrigin("/home/me/plugins/extra.py")
    row = by_name(list_plugins(catalog=test_catalog), "format", "nginx-extra")
    assert (row.status, row.package, row.version, row.description) == ("installed", None, None, "")
    assert row.source == "/home/me/plugins/extra.py"


def test_filters_by_kind_and_status(installed_plugin: None, test_catalog: catalog.Catalog) -> None:
    assert {row.status for row in list_plugins(status="installed", catalog=test_catalog)} == {"installed"}
    assert {row.kind for row in list_plugins(kind="matcher", catalog=test_catalog)} == {"matcher"}
    both = list_plugins(kind="format", status="available", catalog=test_catalog)
    assert [row.name for row in both] == ["sentry", "traefik"]


def test_statuses_are_ordered(installed_plugin: None, test_catalog: catalog.Catalog) -> None:
    order = [row.status for row in list_plugins(catalog=test_catalog)]
    assert order == sorted(order, key={"built-in": 0, "installed": 1, "available": 2}.__getitem__)


def test_an_empty_status_collection_matches_nothing(test_catalog: catalog.Catalog) -> None:
    assert list_plugins(status=(), catalog=test_catalog) == []


@pytest.mark.parametrize(("field", "value"), [("kind", "formatter"), ("status", "missing")])
def test_unknown_filter_values_are_rejected(field: str, value: str) -> None:
    with pytest.raises(ConfigError, match=f"unknown plugin {field}"):
        list_plugins(**{field: value})


def test_plugin_info_returns_every_kind_of_the_name(test_catalog: catalog.Catalog) -> None:
    rows = plugin_info("sentry", catalog=test_catalog)
    assert [(row.kind, row.status) for row in rows] == [("format", "available"), ("reporter", "available")]
    assert [row.kind for row in plugin_info("sentry", kind="reporter", catalog=test_catalog)] == ["reporter"]
    assert [row.status for row in plugin_info("jaccard")] == ["built-in"]


def test_unknown_plugin_suggests_a_close_name(test_catalog: catalog.Catalog) -> None:
    with pytest.raises(UnknownPluginError) as caught:
        plugin_info("traefic", catalog=test_catalog)
    assert caught.value.hint == "did you mean 'traefik'?"
    assert "traefik" in caught.value.known


def test_closest_searches_installed_and_catalog_names(test_catalog: catalog.Catalog) -> None:
    assert closest("traefic", catalog=test_catalog)[0] == "traefik"
    assert closest("jacard", kind="matcher", catalog=test_catalog)[0] == "jaccard"
    assert closest("zzzzzz", catalog=test_catalog) == []
