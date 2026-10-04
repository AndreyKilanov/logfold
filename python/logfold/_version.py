"""Version lookup."""

from __future__ import annotations

from importlib import metadata


def get_version() -> str:
    """Return the installed version of logfold, or ``0+unknown`` when not installed as a distribution."""
    try:
        return metadata.version("logfold")
    except metadata.PackageNotFoundError:
        return "0+unknown"
