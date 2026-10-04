"""Exception hierarchy of logfold.

Every error raised on purpose by the library derives from :class:`LogfoldError`, so callers can catch one type.
"""

from __future__ import annotations


class LogfoldError(Exception):
    """Base class of all logfold errors."""


class ConfigError(LogfoldError, ValueError):
    """An option or configuration value is invalid."""


class FormatError(LogfoldError, ValueError):
    """A log format is invalid, unknown, or could not be detected."""


class SourceError(LogfoldError):
    """An input could not be opened or read."""


class EngineError(LogfoldError, RuntimeError):
    """The engine failed or is unavailable."""
