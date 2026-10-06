"""Log level names, their order and the helpers that work on them."""

from __future__ import annotations

import difflib
from collections.abc import Sequence

from logfold.errors import ConfigError

LEVEL_NAMES = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL")
_LEVEL_ALIASES = {"WARNING": "WARN"}


def summarize_levels(counts: Sequence[int]) -> tuple[str | None, dict[str, int]]:
    """Summarize per-rank level counts.

    Args:
        counts: Record counts indexed by level rank (TRACE..FATAL).

    Returns:
        The most severe level that occurred (or ``None``) and a mapping of level name to count for levels that
        occurred.
    """
    levels = {LEVEL_NAMES[rank]: count for rank, count in enumerate(counts) if count > 0}
    most_severe = next((LEVEL_NAMES[rank] for rank in range(len(counts) - 1, -1, -1) if counts[rank] > 0), None)
    return most_severe, levels


def normalize_level(level: str) -> str:
    """Turn a level name written in any case into the canonical one (``warning`` is accepted for ``WARN``).

    Args:
        level: A level name.

    Returns:
        One of :data:`LEVEL_NAMES`.

    Raises:
        ConfigError: If the name is unknown; the hint suggests the closest level.
    """
    name = _LEVEL_ALIASES.get(level.upper(), level.upper())
    if name not in LEVEL_NAMES:
        close = difflib.get_close_matches(name, LEVEL_NAMES, n=1)
        raise ConfigError(
            f"unknown level {level!r}; use {', '.join(LEVEL_NAMES)}",
            hint=f"did you mean {close[0]!r}?" if close else None,
        )
    return name


def severity(level: str | None) -> int:
    """Return the rank of a level name (0 for ``TRACE``), or -1 for ``None`` and for a name that is not a level."""
    return LEVEL_NAMES.index(level) if level in LEVEL_NAMES else -1


def at_least(level: str | None, minimum: str) -> bool:
    """Tell whether ``level`` is a known level at or above ``minimum``.

    Args:
        level: A level name, or ``None``.
        minimum: A canonical level name.

    Returns:
        ``False`` for ``None`` and for names that are not levels.
    """
    return severity(level) >= 0 and severity(level) >= severity(minimum)
