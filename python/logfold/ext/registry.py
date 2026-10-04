"""Registries of formats, reporters and diff matchers, with entry point discovery.

Third-party packages plug in through the entry point groups ``logfold.formats``, ``logfold.reporters`` and
``logfold.matchers``. An entry point may reference a :class:`~logfold.ext.formats.FormatSpec`, a
:class:`~logfold.ext.formats.Format`, a reporter or a matcher object (or a zero-argument callable returning one).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from importlib import metadata
from typing import TYPE_CHECKING, Any

from logfold.errors import ConfigError, FormatError
from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.matchers import DiffMatcher
from logfold.ext.reporters import Reporter

if TYPE_CHECKING:
    from logfold.model import AnalysisResult, DiffResult

logger = logging.getLogger("logfold")

GROUP_FORMATS = "logfold.formats"
GROUP_REPORTERS = "logfold.reporters"
GROUP_MATCHERS = "logfold.matchers"

_formats: dict[str, FormatSpec | Format] = {}
_reporters: dict[str, Reporter] = {}
_matchers: dict[str, DiffMatcher] = {}
_plugins_loaded = False
_origins: dict[tuple[str, str], str] = {}
_SPEC_TYPES = (PlainFormat, JsonFormat, RegexFormat)


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
    }
    for group, (kind, load) in targets.items():
        for entry in metadata.entry_points(group=group):
            try:
                name = load(entry.name, entry.load())
            except Exception:
                logger.warning("failed to load logfold plugin %s from group %s", entry.name, group, exc_info=True)
                continue
            _origins[(kind, name)] = _origin(entry)


def _load_format(name: str, obj: Any) -> str:
    register_format(name, _resolve(obj))
    return name


def _load_reporter(_name: str, obj: Any) -> str:
    reporter = _resolve(obj)
    register_reporter(reporter)
    return str(reporter.name)


def _load_matcher(_name: str, obj: Any) -> str:
    matcher = _resolve(obj)
    register_matcher(matcher)
    return str(matcher.name)


def _origin(entry: metadata.EntryPoint) -> str:
    dist = getattr(entry, "dist", None)
    if dist is None:
        return entry.value
    return f"{dist.name} {dist.version}"


def plugin_sources() -> list[tuple[str, str, str]]:
    """Return every registered format, reporter and matcher with the place it came from.

    Returns:
        Sorted ``(kind, name, source)`` triples. ``kind`` is ``format``, ``reporter`` or ``matcher``; ``source`` is
        ``built-in`` or ``<distribution> <version>`` of the installed plugin package.
    """
    load_plugins()
    rows = [
        (kind, name, _origins.get((kind, name), "built-in"))
        for kind, names in (("format", _formats), ("reporter", _reporters), ("matcher", _matchers))
        for name in names
    ]
    return sorted(rows)


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
        known = ", ".join(sorted(_formats))
        raise FormatError(f"unknown format {name!r}; known formats: {known}") from None
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
        known = ", ".join(sorted(_reporters))
        raise ConfigError(f"unknown reporter {name!r}; known reporters: {known}") from None


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
        known = ", ".join(sorted(_matchers))
        raise ConfigError(f"unknown diff matcher {name!r}; known matchers: {known}") from None


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
