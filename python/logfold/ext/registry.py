"""Registries of formats, reporters and diff matchers, with entry point discovery.

Third-party packages plug in through the entry point groups ``logfold.formats``, ``logfold.reporters`` and
``logfold.matchers``. An entry point may reference a :class:`~logfold.ext.formats.FormatSpec`, a
:class:`~logfold.ext.formats.Format`, a reporter or a matcher object (or a zero-argument callable returning one).
"""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from collections.abc import Callable
from importlib import metadata
from pathlib import Path
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
ENV_PLUGIN_PATH = "LOGFOLD_PLUGIN_PATH"
ENV_NO_USER_PLUGINS = "LOGFOLD_NO_USER_PLUGINS"

_formats: dict[str, FormatSpec | Format] = {}
_reporters: dict[str, Reporter] = {}
_matchers: dict[str, DiffMatcher] = {}
_plugins_loaded = False
_origins: dict[tuple[str, str], str] = {}
_explicit_dirs: list[Path] = []
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


def default_plugin_dir() -> Path:
    r"""Return the folder where logfold looks for the user's own plugins.

    Returns:
        ``%APPDATA%\logfold\plugins`` on Windows, ``$XDG_CONFIG_HOME/logfold/plugins`` or
        ``~/.config/logfold/plugins`` elsewhere. The folder does not have to exist.
    """
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "logfold" / "plugins"


def plugin_directories() -> list[Path]:
    """Return the folders that are searched for plugins without being asked.

    These are the user plugin folder and the folders of ``LOGFOLD_PLUGIN_PATH`` (separated like ``PATH``). The current
    directory is never searched. ``LOGFOLD_NO_USER_PLUGINS=1`` switches all of them off.

    Returns:
        The folders, in loading order, without duplicates.
    """
    if os.environ.get(ENV_NO_USER_PLUGINS, "") not in ("", "0"):
        return []
    folders = [default_plugin_dir()]
    folders.extend(Path(part) for part in os.environ.get(ENV_PLUGIN_PATH, "").split(os.pathsep) if part)
    unique: list[Path] = []
    for folder in folders:
        if folder not in unique:
            unique.append(folder)
    return unique


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


def _is_unsafe(path: Path) -> bool:
    """Tell whether another user could have planted or changed ``path``.

    On POSIX a path is unsafe when everybody can write to it or when it belongs to somebody other than the current user
    or root. Group write access is allowed, because many systems give every user a private group. On Windows the check
    is skipped: the plugin folder lives in the user's own profile.
    """
    if sys.platform == "win32":
        return False
    info = path.stat()
    return bool(info.st_mode & 0o002) or info.st_uid not in (os.getuid(), 0)


def _load_directory(directory: Path, warn_if_missing: bool) -> None:
    if not directory.is_dir():
        if warn_if_missing:
            logger.warning("logfold plugin folder %s does not exist", directory)
        return
    if _is_unsafe(directory):
        logger.warning("skipping logfold plugin folder %s: other users can change it", directory)
        return
    for entry in sorted(directory.iterdir(), key=lambda item: item.name):
        if entry.name.startswith(("_", ".")):
            continue
        if entry.is_file() and entry.suffix == ".py":
            _load_user_module(entry, entry.stem, package=False)
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            _load_user_module(entry / "__init__.py", entry.name, package=True)


def _load_user_module(path: Path, stem: str, package: bool) -> None:
    if _is_unsafe(path):
        logger.warning("skipping logfold plugin %s: other users can change it", path)
        return
    module_name = "logfold_user_plugin_" + "".join(c if c.isalnum() else "_" for c in stem)
    spec = importlib.util.spec_from_file_location(
        module_name, path, submodule_search_locations=[str(path.parent)] if package else None
    )
    if spec is None or spec.loader is None:
        logger.warning("cannot load logfold plugin %s", path)
        return
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        logger.warning("failed to load logfold plugin %s", path, exc_info=True)
        return
    for kind, attribute, load in (
        ("format", "FORMATS", _load_format),
        ("reporter", "REPORTERS", _load_reporter),
        ("matcher", "MATCHERS", _load_matcher),
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
            _origins[(kind, name)] = str(path)


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
