"""One list of every format, reporter and diff matcher: built in, installed, or available from the catalog.

The registry (:mod:`logfold.ext.registry`) knows what is loaded, the catalog (:mod:`logfold.plugins.catalog`) knows what
could be installed. This module joins them, so that callers do not have to guess plugin names. Nothing here touches the
network: the catalog is the one bundled with logfold unless the caller passes another.
"""

from __future__ import annotations

import difflib
from collections.abc import Collection
from dataclasses import dataclass
from importlib import metadata
from typing import TYPE_CHECKING

from logfold.errors import ConfigError, UnknownPluginError
from logfold.ext import registry

if TYPE_CHECKING:
    from logfold.plugins.catalog import Catalog, CatalogEntry

__all__ = ["KINDS", "STATUSES", "PluginInfo", "closest", "list_plugins", "plugin_info"]

KINDS = ("format", "reporter", "matcher")
STATUSES = ("built-in", "installed", "available")
_STATUS_ORDER = {status: index for index, status in enumerate(STATUSES)}


@dataclass(frozen=True, slots=True)
class PluginInfo:
    """One format, reporter or diff matcher and where it stands.

    Attributes:
        kind: ``format``, ``reporter`` or ``matcher``.
        name: The name used in options such as ``--format``.
        status: ``built-in``, ``installed`` (a package, or a file in a plugin folder) or ``available`` (in the catalog,
            not installed).
        source: ``built-in``, ``<package> <version>``, the path of a plugin file, or the catalog the plugin is from.
        package: Distribution name, if the plugin comes from a package or is listed in the catalog.
        version: Installed version of that package, if it is installed.
        description: One line about the plugin, or an empty string.
        requirement: What ``pip install`` would get for an available plugin, otherwise ``None``.
        install: The logfold command that installs an available plugin, otherwise ``None``.
        homepage: ``https`` link of an available plugin, if the catalog has one.
    """

    kind: str
    name: str
    status: str
    source: str
    package: str | None = None
    version: str | None = None
    description: str = ""
    requirement: str | None = None
    install: str | None = None
    homepage: str | None = None


def _summary(package: str) -> str:
    try:
        return str(metadata.metadata(package)["Summary"] or "")
    except (metadata.PackageNotFoundError, KeyError, ValueError):
        return ""


def _registered(catalog: Catalog) -> list[PluginInfo]:
    by_package = {entry.package: entry for entry in catalog.entries}
    origins = registry.plugin_origins()
    rows: list[PluginInfo] = []
    for kind, name, source in registry.plugin_sources():
        origin = origins.get((kind, name))
        if origin is None:
            rows.append(PluginInfo(kind, name, "built-in", source))
            continue
        entry = by_package.get(origin.package or "")
        description = entry.description if entry is not None else _summary(origin.package) if origin.package else ""
        rows.append(PluginInfo(kind, name, "installed", source, origin.package, origin.version, description))
    return rows


def _available(entry: CatalogEntry, source: str) -> list[PluginInfo]:
    return [
        PluginInfo(
            kind,
            entry.name,
            "available",
            source,
            entry.package,
            None,
            entry.description,
            entry.requirement,
            f"logfold plugins install {entry.name}",
            entry.homepage,
        )
        for kind in entry.kinds
    ]


def list_plugins(
    kind: str | None = None, status: str | Collection[str] | None = None, catalog: Catalog | None = None
) -> list[PluginInfo]:
    """List the plugins with their status.

    Args:
        kind: Keep only ``format``, ``reporter`` or ``matcher``.
        status: Keep only plugins with this status, or any of these: ``built-in``, ``installed``, ``available``.
        catalog: Where the ``available`` plugins come from. By default the catalog bundled with logfold, which needs no
            network; load another one with :func:`logfold.plugins.catalog.load`.

    Returns:
        Built-in plugins first, then installed, then available; each group sorted by kind and name.

    Raises:
        ConfigError: If ``kind`` or ``status`` is not one of the allowed values.
    """
    from logfold.plugins import catalog as plugin_catalog  # noqa: PLC0415 - slow imports

    if kind is not None and kind not in KINDS:
        raise ConfigError(f"unknown plugin kind {kind!r}; use one of: {', '.join(KINDS)}")
    wanted = None if status is None else {status} if isinstance(status, str) else set(status)
    for value in (wanted or set()) - set(STATUSES):
        raise ConfigError(f"unknown plugin status {value!r}; use one of: {', '.join(STATUSES)}")
    loaded = catalog if catalog is not None else plugin_catalog.load_bundled()
    rows = _registered(loaded)
    taken = {(row.kind, row.name) for row in rows}
    for entry in plugin_catalog.new_plugins(loaded):
        rows.extend(row for row in _available(entry, loaded.source) if (row.kind, row.name) not in taken)
    rows = [row for row in rows if (kind is None or row.kind == kind) and (wanted is None or row.status in wanted)]
    return sorted(rows, key=lambda row: (_STATUS_ORDER[row.status], row.kind, row.name))


def closest(name: str, kind: str | None = None, catalog: Catalog | None = None, limit: int = 3) -> list[str]:
    """Find the plugin names that look most like ``name``.

    Args:
        name: What the user typed.
        kind: Search only this kind of plugin.
        catalog: Catalog to search besides the installed plugins; the bundled one by default.
        limit: How many names to return at most.

    Returns:
        The closest names, best first, without duplicates.
    """
    names = sorted({row.name for row in list_plugins(kind=kind, catalog=catalog)})
    return difflib.get_close_matches(name, names, n=limit)


def plugin_info(name: str, kind: str | None = None, catalog: Catalog | None = None) -> list[PluginInfo]:
    """Describe the plugin called ``name``.

    A name can belong to more than one kind (``json`` is a format and a reporter), so a list comes back.

    Args:
        name: The plugin name.
        kind: Look only among this kind.
        catalog: Catalog for ``available`` plugins; the bundled one by default.

    Returns:
        One record per kind that has a plugin of this name.

    Raises:
        UnknownPluginError: If there is none; ``hint`` names the closest plugins.
    """
    found = [row for row in list_plugins(kind=kind, catalog=catalog) if row.name == name]
    if not found:
        raise UnknownPluginError(name, sorted({row.name for row in list_plugins(kind=kind, catalog=catalog)}))
    return found
