"""Facts about the installation: versions, the native engine and what is registered."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from logfold._version import get_version
from logfold.engines import native
from logfold.ext import registry


@dataclass(frozen=True, slots=True)
class Info:
    """What :func:`logfold.info` reports; the same facts as ``logfold info``.

    Attributes:
        version: The logfold version.
        python: The Python version, for example ``3.13.1``.
        native_available: Whether the native engine can be used; when ``False`` the slow pure-Python engine runs.
        core_version: Version of the native extension, or ``None`` when it is unavailable.
        contract_version: Version of the contract between the Python layer and the extension, or ``None``.
        algo_version: Version of the template algorithm, or ``None``.
        formats: Names of the registered formats, sorted.
        reporters: Names of the registered reporters, sorted.
        matchers: Names of the registered diff matchers, sorted.
    """

    version: str
    python: str
    native_available: bool
    core_version: str | None
    contract_version: int | None
    algo_version: int | None
    formats: tuple[str, ...]
    reporters: tuple[str, ...]
    matchers: tuple[str, ...]


def info() -> Info:
    """Collect the installation facts, which is also what a bug report needs.

    Returns:
        The facts. Registered plugins are loaded first, so their names are included.
    """
    versions = native.core_versions() if native.is_available() else None
    return Info(
        version=get_version(),
        python=sys.version.split()[0],
        native_available=versions is not None,
        core_version=None if versions is None else str(versions["core"]),
        contract_version=None if versions is None else int(versions["contract"]),
        algo_version=None if versions is None else int(versions["algo"]),
        formats=tuple(registry.format_names()),
        reporters=tuple(registry.reporter_names()),
        matchers=tuple(registry.matcher_names()),
    )
