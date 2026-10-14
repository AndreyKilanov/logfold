"""Registries of formats, reporters, diff matchers, mask sets and sources, with entry point discovery.

Third-party packages plug in through the entry point groups ``logfold.formats``, ``logfold.reporters``,
``logfold.matchers``, ``logfold.masks`` and ``logfold.sources``. An entry point may reference a
:class:`~logfold.ext.formats.FormatSpec`, a :class:`~logfold.ext.formats.Format`, a reporter, a matcher, a
:class:`~logfold.ext.mask_sets.MaskSet` or a :class:`~logfold.ext.sources.Source` object (or a zero-argument callable
returning one).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple

from logfold.errors import (
    ConfigError,
    UnknownFormatError,
    UnknownMaskSetError,
    UnknownMatcherError,
    UnknownReporterError,
    UnknownSourceError,
    UnknownSuffixError,
)
from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.mask_sets import MaskSet
from logfold.ext.matchers import DiffMatcher
from logfold.ext.plugin_folders import import_plugin_modules, plugin_directories
from logfold.ext.reporters import Reporter
from logfold.ext.sources import Source

if TYPE_CHECKING:
    from logfold.model import AnalysisResult, DiffResult

logger = logging.getLogger("logfold")

GROUP_FORMATS = "logfold.formats"
GROUP_REPORTERS = "logfold.reporters"
GROUP_MATCHERS = "logfold.matchers"
GROUP_MASKS = "logfold.masks"
GROUP_SOURCES = "logfold.sources"
SUFFIX_REPORTERS = {
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".txt": "text",
    ".md": "markdown",
    ".csv": "csv",
    ".xml": "junit",
    ".prom": "prometheus",
}
"""Report file suffixes and the built-in reporter each one selects."""

_formats: dict[str, FormatSpec | Format] = {}
_reporters: dict[str, Reporter] = {}
_matchers: dict[str, DiffMatcher] = {}
_mask_sets: dict[str, MaskSet] = {}
_sources: dict[str, Source] = {}
_plugins_loaded = False
_origins: dict[tuple[str, str], PluginOrigin] = {}
_explicit_dirs: list[Path] = []
_SPEC_TYPES = (PlainFormat, JsonFormat, RegexFormat)
BUILT_IN = "built-in"


class PluginOrigin(NamedTuple):
    """Where a registered plugin came from.

    Attributes:
        label: Text for people: ``<package> <version>``, the path of a file, or the entry point value.
        package: Distribution name when the plugin comes from an installed package, otherwise ``None``.
        version: Version of that distribution, otherwise ``None``.
    """

    label: str
    package: str | None = None
    version: str | None = None


def register_format(name: str, spec: FormatSpec | Format) -> None:
    """Register a format under ``name`` (replaces an existing registration).

    Args:
        name: Format name.
        spec: A format specification or an object with a ``spec()`` method.
    """
    _formats[name] = spec


def register_reporter(reporter: Reporter) -> None:
    """Register a reporter under its ``name`` (replaces an existing registration).

    Args:
        reporter: Reporter instance.
    """
    _reporters[reporter.name] = reporter


def register_matcher(matcher: DiffMatcher) -> None:
    """Register a diff matcher under its ``name`` (replaces an existing registration).

    Args:
        matcher: Matcher instance.
    """
    _matchers[matcher.name] = matcher


def register_mask_set(mask_set: MaskSet) -> None:
    """Register a mask set under its ``name`` (replaces an existing registration).

    Args:
        mask_set: The set.
    """
    _mask_sets[mask_set.name] = mask_set


def register_source(source: Source) -> None:
    """Register a source under its ``name`` (replaces an existing registration).

    Args:
        source: The source.
    """
    _sources[source.name] = source


def _resolve(obj: Any) -> Any:
    if isinstance(obj, type):
        return obj()
    if isinstance(obj, _SPEC_TYPES) or any(hasattr(obj, attr) for attr in ("spec", "render", "match")):
        return obj
    return obj() if callable(obj) else obj


def load_plugins(force: bool = False) -> None:
    """Discover and register plugins from entry points. Runs once unless ``force`` is set.

    A plugin that fails to load is skipped with a warning; it never breaks the library.

    Args:
        force: Load again even if plugins were already loaded.
    """
    global _plugins_loaded  # noqa: PLW0603 - module-level cache flag
    if _plugins_loaded and not force:
        return
    _plugins_loaded = True
    targets: dict[str, tuple[str, Callable[[str, Any], str]]] = {
        GROUP_FORMATS: ("format", _load_format),
        GROUP_REPORTERS: ("reporter", _load_reporter),
        GROUP_MATCHERS: ("matcher", _load_matcher),
        GROUP_MASKS: ("mask", _load_mask_set),
        GROUP_SOURCES: ("source", _load_source),
    }
    discovered = metadata.entry_points()
    for group, (kind, load) in targets.items():
        for entry in discovered.select(group=group):
            try:
                name = load(entry.name, entry.load())
            except Exception:
                logger.warning("failed to load logfold plugin %s from group %s", entry.name, group, exc_info=True)
                continue
            _origins[(kind, name)] = _origin(entry)
    for directory in plugin_directories():
        _load_directory(directory, warn_if_missing=False)
    for directory in _explicit_dirs:
        _load_directory(directory, warn_if_missing=True)


def _load_format(name: str, obj: Any) -> str:
    if not name:
        raise TypeError("a format needs a name")
    register_format(name, _resolve(obj))
    return name


def _load_reporter(_name: str, obj: Any) -> str:
    reporter = _resolve(obj)
    if not isinstance(reporter, Reporter):
        raise TypeError("a reporter needs name, kinds and render()")
    register_reporter(reporter)
    return str(reporter.name)


def _load_matcher(_name: str, obj: Any) -> str:
    matcher = _resolve(obj)
    if not isinstance(matcher, DiffMatcher):
        raise TypeError("a matcher needs name and match()")
    register_matcher(matcher)
    return str(matcher.name)


def _load_mask_set(_name: str, obj: Any) -> str:
    mask_set = obj() if callable(obj) and not isinstance(obj, MaskSet) else obj
    if not isinstance(mask_set, MaskSet):
        raise TypeError("a mask set plugin must be a MaskSet (or a function that returns one)")
    register_mask_set(mask_set)
    return mask_set.name


def _load_source(_name: str, obj: Any) -> str:
    source = _resolve(obj)
    if not isinstance(source, Source):
        raise TypeError("a source needs name, description, platforms and command()")
    register_source(source)
    return str(source.name)


def _origin(entry: metadata.EntryPoint) -> PluginOrigin:
    dist = getattr(entry, "dist", None)
    if dist is None:
        return PluginOrigin(entry.value)
    return PluginOrigin(f"{dist.name} {dist.version}", dist.name, dist.version)


def plugin_sources() -> list[tuple[str, str, str]]:
    """Return every registered format, reporter, matcher, mask set and source with the place it came from.

    Returns:
        Sorted ``(kind, name, source)`` triples. ``kind`` is ``format``, ``reporter``, ``matcher``, ``mask`` or
        ``source``; the last item is ``built-in`` or ``<distribution> <version>`` of the installed plugin package.
    """
    load_plugins()
    rows = [
        (kind, name, _origins.get((kind, name), PluginOrigin(BUILT_IN)).label)
        for kind, names in (
            ("format", _formats),
            ("reporter", _reporters),
            ("matcher", _matchers),
            ("mask", _mask_sets),
            ("source", _sources),
        )
        for name in names
    ]
    return sorted(rows)


def plugin_origins() -> dict[tuple[str, str], PluginOrigin]:
    """Return where every plugin that is not built in came from.

    Returns:
        A copy that maps ``(kind, name)`` to its :class:`PluginOrigin`. Built-in plugins are absent.
    """
    load_plugins()
    return dict(_origins)


def add_plugin_directory(path: str | os.PathLike[str]) -> None:
    """Load the plugins of a folder, now or as soon as plugins are loaded.

    Use it for a folder that the caller chose explicitly; it is not affected by ``LOGFOLD_NO_USER_PLUGINS``.

    Args:
        path: Folder with plugin modules.
    """
    folder = Path(path)
    _explicit_dirs.append(folder)
    if _plugins_loaded:
        _load_directory(folder, warn_if_missing=True)


def _load_directory(directory: Path, warn_if_missing: bool) -> None:
    for path, module in import_plugin_modules(directory, warn_if_missing):
        for kind, attribute, load in (
            ("format", "FORMATS", _load_format),
            ("reporter", "REPORTERS", _load_reporter),
            ("matcher", "MATCHERS", _load_matcher),
            ("mask", "MASKS", _load_mask_set),
            ("source", "SOURCES", _load_source),
        ):
            items = getattr(module, attribute, ())
            if not isinstance(items, (list, tuple)):
                logger.warning("logfold plugin %s: %s must be a list", path, attribute)
                continue
            for item in items:
                try:
                    name = load(str(getattr(item, "name", "")), item)
                except Exception:
                    logger.warning("failed to register a %s from logfold plugin %s", kind, path, exc_info=True)
                    continue
                _origins[(kind, name)] = PluginOrigin(str(path))


def get_format(name: str) -> FormatSpec:
    """Return the specification registered under ``name``.

    Args:
        name: Format name.

    Returns:
        The declarative specification.

    Raises:
        FormatError: If the name is unknown.
    """
    load_plugins()
    try:
        entry = _formats[name]
    except KeyError:
        raise UnknownFormatError(name, _formats) from None
    return entry if isinstance(entry, _SPEC_TYPES) else entry.spec()


def format_names() -> list[str]:
    """Return the sorted names of all registered formats."""
    load_plugins()
    return sorted(_formats)


def get_reporter(name: str) -> Reporter:
    """Return the reporter registered under ``name``.

    Args:
        name: Reporter name.

    Returns:
        The reporter.

    Raises:
        ConfigError: If the name is unknown.
    """
    load_plugins()
    try:
        return _reporters[name]
    except KeyError:
        raise UnknownReporterError(name, _reporters) from None


def reporter_names() -> list[str]:
    """Return the sorted names of all registered reporters."""
    load_plugins()
    return sorted(_reporters)


def get_matcher(name: str) -> DiffMatcher:
    """Return the diff matcher registered under ``name``.

    Args:
        name: Matcher name.

    Returns:
        The matcher.

    Raises:
        ConfigError: If the name is unknown.
    """
    load_plugins()
    try:
        return _matchers[name]
    except KeyError:
        raise UnknownMatcherError(name, _matchers) from None


def matcher_names() -> list[str]:
    """Return the sorted names of all registered diff matchers."""
    load_plugins()
    return sorted(_matchers)


def get_mask_set(name: str) -> MaskSet:
    """Return the mask set registered under ``name``.

    Args:
        name: Mask set name.

    Returns:
        The set.

    Raises:
        UnknownMaskSetError: If the name is unknown (a :class:`~logfold.errors.ConfigError`).
    """
    load_plugins()
    try:
        return _mask_sets[name]
    except KeyError:
        raise UnknownMaskSetError(name, _mask_sets) from None


def mask_set_names() -> list[str]:
    """Return the sorted names of all registered mask sets."""
    load_plugins()
    return sorted(_mask_sets)


def get_source(name: str) -> Source:
    """Return the source registered under ``name``.

    Args:
        name: Source name.

    Returns:
        The source.

    Raises:
        UnknownSourceError: If the name is unknown (a :class:`~logfold.errors.ConfigError`).
    """
    load_plugins()
    try:
        return _sources[name]
    except KeyError:
        raise UnknownSourceError(name, _sources) from None


def source_names() -> list[str]:
    """Return the sorted names of all registered sources."""
    load_plugins()
    return sorted(_sources)


def reporter_for_suffix(path: str | os.PathLike[str]) -> str:
    """Return the name of the reporter that a report file name selects, from its suffix.

    Args:
        path: The report file name; the suffix is compared in lower case (see :data:`SUFFIX_REPORTERS`).

    Returns:
        The reporter name.

    Raises:
        UnknownSuffixError: If the name has no suffix or an unknown one.
    """
    try:
        return SUFFIX_REPORTERS[Path(path).suffix.lower()]
    except KeyError:
        raise UnknownSuffixError(os.fspath(path), SUFFIX_REPORTERS) from None


def render(result: AnalysisResult | DiffResult, reporter: str, **options: object) -> str:
    """Render ``result`` with the named reporter.

    Args:
        result: Result to render.
        reporter: Reporter name.
        **options: Reporter options.

    Returns:
        The rendered text.

    Raises:
        ConfigError: If the reporter does not support this kind of result.
    """
    chosen = get_reporter(reporter)
    kind = "diff" if hasattr(result, "new_templates") else "analysis"
    if kind not in chosen.kinds:
        raise ConfigError(f"reporter {reporter!r} does not support {kind} results")
    return chosen.render(result, **options)
