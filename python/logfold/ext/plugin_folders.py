"""The folders that hold the user's own plugins, and the import of the plugin modules found in them."""

from __future__ import annotations

import importlib.util
import logging
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

logger = logging.getLogger("logfold")

ENV_PLUGIN_PATH = "LOGFOLD_PLUGIN_PATH"
ENV_NO_USER_PLUGINS = "LOGFOLD_NO_USER_PLUGINS"


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


def import_plugin_modules(directory: Path, warn_if_missing: bool) -> Iterator[tuple[Path, ModuleType]]:
    """Import the plugin modules of a folder, skipping what other users could have changed.

    A module that fails to import is skipped with a warning.

    Args:
        directory: The plugin folder.
        warn_if_missing: Warn when the folder does not exist (it was named explicitly).

    Yields:
        The path of each plugin and its imported module.
    """
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
            path, package = entry, False
        elif entry.is_dir() and (entry / "__init__.py").is_file():
            path, package = entry / "__init__.py", True
        else:
            continue
        module = _import_module(path, entry.stem if not package else entry.name, package)
        if module is not None:
            yield path, module


def _import_module(path: Path, stem: str, package: bool) -> ModuleType | None:
    if _is_unsafe(path):
        logger.warning("skipping logfold plugin %s: other users can change it", path)
        return None
    module_name = "logfold_user_plugin_" + "".join(c if c.isalnum() else "_" for c in stem)
    spec = importlib.util.spec_from_file_location(
        module_name, path, submodule_search_locations=[str(path.parent)] if package else None
    )
    if spec is None or spec.loader is None:
        logger.warning("cannot load logfold plugin %s", path)
        return None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        logger.warning("failed to load logfold plugin %s", path, exc_info=True)
        return None
    return module
