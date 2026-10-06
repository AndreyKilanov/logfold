"""Catalog of installable plugins: bundled with the wheel, optionally read from a file or fetched over HTTPS.

The catalog is data from an untrusted place (a file, or the network), so it is validated strictly: names and version
specifiers must match fixed patterns (nothing that pip could read as an option), text must be printable, and size and
entry count are capped. Nothing here runs at import time and nothing touches the network unless the caller asks for it.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from importlib import metadata, resources, util
from pathlib import Path
from typing import Any

from logfold._version import get_version
from logfold.errors import ConfigError, SourceError

__all__ = [
    "DEFAULT_CATALOG_URL",
    "ENV_OFFLINE",
    "Catalog",
    "CatalogEntry",
    "fetch",
    "install",
    "is_installed",
    "load",
    "load_bundled",
    "new_plugins",
    "parse_catalog",
    "require_compatible",
]

SCHEMA_VERSION = 1
DEFAULT_CATALOG_URL = "https://raw.githubusercontent.com/AndreyKilanov/logfold/main/python/logfold/plugins/catalog.json"
ENV_OFFLINE = "LOGFOLD_OFFLINE"
KINDS = ("format", "reporter", "matcher")
MAX_BYTES = 256 * 1024
MAX_ENTRIES = 500
TIMEOUT_SECONDS = 10.0

_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ONE_SPECIFIER = r"(?:==|!=|<=|>=|~=|<|>)\s*[0-9][0-9A-Za-z.*+!_-]*"
_MIN_VERSION = re.compile(r"^[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}$")
_LEADING_NUMBERS = re.compile(r"[0-9]+(?:\.[0-9]+)*")
_SPECIFIER = re.compile(rf"^(?:{_ONE_SPECIFIER}(?:\s*,\s*{_ONE_SPECIFIER})*)?$")


@dataclass(frozen=True, slots=True)
class CatalogEntry:
    """A plugin package that can be installed.

    Attributes:
        name: Short name used by ``logfold plugins install``.
        kinds: What the package adds: ``format``, ``reporter`` and/or ``matcher``.
        package: Name of the package on PyPI.
        specifier: Version constraint such as ``>=0.2,<1``, or an empty string.
        description: One line for people.
        homepage: ``https`` link to the project, if any.
        min_logfold: Oldest logfold version the plugin works with, as ``X.Y.Z``, or ``None`` if it does not say.
    """

    name: str
    kinds: tuple[str, ...]
    package: str
    specifier: str
    description: str
    homepage: str | None
    min_logfold: str | None = None

    @property
    def requirement(self) -> str:
        """The argument passed to ``pip install``."""
        return self.package + self.specifier

    def fits(self, version: str | None = None) -> bool:
        """Tell whether the plugin works with a logfold version.

        Args:
            version: The logfold version to check; the running one by default. A development checkout
                (``0+unknown``) and a version that cannot be read are treated as fitting.

        Returns:
            ``False`` only if ``min_logfold`` is set and the version is older.
        """
        if self.min_logfold is None:
            return True
        current = version if version is not None else get_version()
        if current.startswith("0+unknown"):
            return True
        found = _numbers(current)
        return not found or found >= _numbers(self.min_logfold)


@dataclass(frozen=True, slots=True)
class Catalog:
    """A validated list of installable plugins.

    Attributes:
        entries: The plugins.
        source: Where the catalog came from: ``bundled``, a file path or an URL.
    """

    entries: tuple[CatalogEntry, ...]
    source: str

    def find(self, name: str) -> CatalogEntry | None:
        """Return the entry called ``name``.

        Args:
            name: Short plugin name.

        Returns:
            The entry, or ``None``.
        """
        return next((entry for entry in self.entries if entry.name == name), None)


def _numbers(version: str) -> tuple[int, ...]:
    match = _LEADING_NUMBERS.match(version)
    if match is None:
        return ()
    parts = [int(part) for part in match.group().split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def _fail(source: str, reason: str) -> ConfigError:
    return ConfigError(f"invalid plugin catalog ({source}): {reason}")


def _text(value: object, field: str, source: str, limit: int, required: bool = True) -> str:
    if not isinstance(value, str):
        raise _fail(source, f"{field} must be a string")
    if required and not value:
        raise _fail(source, f"{field} must not be empty")
    if len(value) > limit or not value.isprintable():
        raise _fail(source, f"{field} is too long or has control characters")
    return value


def _entry(raw: object, source: str) -> CatalogEntry:
    if not isinstance(raw, dict):
        raise _fail(source, "every plugin must be an object")
    name = _text(raw.get("name"), "name", source, 64)
    package = _text(raw.get("package"), "package", source, 64)
    if not _NAME.match(name) or not _NAME.match(package):
        raise _fail(source, f"unsafe name {name!r} or package {package!r}")
    specifier = _text(raw.get("specifier", ""), "specifier", source, 64, required=False)
    if not _SPECIFIER.match(specifier):
        raise _fail(source, f"unsupported version specifier {specifier!r}")
    kinds = raw.get("kinds")
    if not isinstance(kinds, list) or not kinds or any(kind not in KINDS for kind in kinds):
        raise _fail(source, f"kinds of {name!r} must be a non-empty list of {', '.join(KINDS)}")
    description = _text(raw.get("description", ""), "description", source, 300, required=False)
    homepage = raw.get("homepage")
    if homepage is not None:
        homepage = _text(homepage, "homepage", source, 200)
        if not homepage.startswith("https://"):
            raise _fail(source, "homepage must be an https link")
    minimum = raw.get("min_logfold")
    if minimum is not None:
        minimum = _text(minimum, "min_logfold", source, 16)
        if not _MIN_VERSION.match(minimum):
            raise _fail(source, f"min_logfold of {name!r} must look like 0.4.0")
    return CatalogEntry(name, tuple(kinds), package, "".join(specifier.split()), description, homepage, minimum)


def parse_catalog(data: object, source: str) -> Catalog:
    """Validate decoded JSON and build a catalog.

    Args:
        data: Decoded JSON document.
        source: Label used in error messages and results.

    Returns:
        The catalog.

    Raises:
        ConfigError: If the document does not follow the catalog schema.
    """
    if not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION:
        raise _fail(source, f"expected an object with schema_version {SCHEMA_VERSION}")
    plugins = data.get("plugins")
    if not isinstance(plugins, list) or len(plugins) > MAX_ENTRIES:
        raise _fail(source, f"plugins must be a list of at most {MAX_ENTRIES} entries")
    entries = tuple(_entry(raw, source) for raw in plugins)
    if len({entry.name for entry in entries}) != len(entries):
        raise _fail(source, "plugin names must be unique")
    return Catalog(entries, source)


def _decode(raw: bytes, source: str) -> Catalog:
    if len(raw) > MAX_BYTES:
        raise _fail(source, f"larger than {MAX_BYTES} bytes")
    try:
        data: Any = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _fail(source, f"not valid JSON: {error}") from error
    return parse_catalog(data, source)


def load_bundled() -> Catalog:
    """Return the catalog that ships with this version of logfold. Works offline.

    Returns:
        The bundled catalog.
    """
    raw = resources.files("logfold.plugins").joinpath("catalog.json").read_bytes()
    return _decode(raw, "bundled")


def fetch(url: str) -> Catalog:
    """Download and validate a catalog over HTTPS.

    Args:
        url: An ``https`` URL.

    Returns:
        The catalog.

    Raises:
        ConfigError: If the URL is not https, network access is disabled by ``LOGFOLD_OFFLINE``, or the document is
            invalid.
        SourceError: If the download fails.
    """
    if not url.startswith("https://"):
        raise ConfigError("a plugin catalog can only be fetched over https")
    if os.environ.get(ENV_OFFLINE, "") not in ("", "0"):
        raise ConfigError(f"network access is disabled by {ENV_OFFLINE}")
    request = urllib.request.Request(
        url, headers={"User-Agent": f"logfold/{get_version()}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            final = response.geturl()
            raw = response.read(MAX_BYTES + 1)
    except (urllib.error.URLError, OSError, ValueError) as error:
        raise SourceError(f"cannot fetch the plugin catalog {url}: {error}") from error
    if not final.startswith("https://"):
        raise SourceError(f"the plugin catalog {url} redirected to a non-https address")
    return _decode(raw, url)


def load(source: str | None = None, online: bool = False) -> Catalog:
    """Load a catalog from the chosen place.

    Args:
        source: A file path or an ``https`` URL. Wins over ``online``.
        online: Fetch :data:`DEFAULT_CATALOG_URL` instead of using the bundled catalog.

    Returns:
        The catalog.

    Raises:
        ConfigError: If the catalog is invalid or network access is not allowed.
        SourceError: If the catalog cannot be read.
    """
    if source is not None:
        if source.startswith(("https://", "http://")):
            return fetch(source)
        try:
            with Path(source).open("rb") as handle:
                return _decode(handle.read(MAX_BYTES + 1), source)
        except OSError as error:
            raise SourceError(f"cannot read the plugin catalog {source!r}: {error}") from error
    if online:
        return fetch(DEFAULT_CATALOG_URL)
    return load_bundled()


def is_installed(package: str) -> bool:
    """Tell whether a distribution is installed in the current environment.

    Args:
        package: Distribution name.

    Returns:
        ``True`` if it is installed.
    """
    try:
        metadata.distribution(package)
    except metadata.PackageNotFoundError:
        return False
    return True


def new_plugins(catalog: Catalog, installed: Callable[[str], bool] = is_installed) -> tuple[CatalogEntry, ...]:
    """Return the catalog plugins whose package is not installed yet.

    Args:
        catalog: The catalog.
        installed: Predicate telling whether a package is installed.

    Returns:
        The entries to offer, in catalog order.
    """
    return tuple(entry for entry in catalog.entries if not installed(entry.package))


def require_compatible(entry: CatalogEntry, version: str | None = None) -> None:
    """Refuse a plugin that needs a newer logfold than the running one.

    Args:
        entry: A validated catalog entry.
        version: The logfold version to check; the running one by default.

    Raises:
        ConfigError: If the plugin needs a newer logfold; ``hint`` says to upgrade.
    """
    if not entry.fits(version):
        raise ConfigError(
            f"plugin {entry.name!r} needs logfold {entry.min_logfold} or newer; this is "
            f"{version if version is not None else get_version()}",
            hint="upgrade logfold first, for example: pip install -U logfold",
        )


def install(entry: CatalogEntry, runner: Callable[..., Any] = subprocess.run) -> int:
    """Install a plugin package into the environment that runs logfold.

    Uses ``pip`` when it is available, otherwise ``uv pip install`` (environments made by ``uv`` have no pip).

    Args:
        entry: A validated catalog entry.
        runner: ``subprocess.run`` compatible callable; replaced in tests.

    Returns:
        The exit code of the installer.

    Raises:
        ConfigError: If the plugin needs a newer logfold, or neither pip nor uv is available in this environment.
    """
    require_compatible(entry)
    if util.find_spec("pip") is not None:
        command = [sys.executable, "-m", "pip", "install", entry.requirement]
    elif (uv := shutil.which("uv")) is not None:
        command = [uv, "pip", "install", "--python", sys.executable, entry.requirement]
    else:
        raise ConfigError(
            f"neither pip nor uv is available in this environment; install {entry.requirement!r} with its package "
            "installer",
            hint=f"for example: uv pip install '{entry.requirement}'",
        )
    return int(runner(command, check=False).returncode)
