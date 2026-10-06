"""Exception hierarchy of logfold.

Every error raised on purpose by the library derives from :class:`LogfoldError`, so callers can catch one type.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable


class LogfoldError(Exception):
    """Base class of all logfold errors.

    Attributes:
        hint: A short suggestion for the next step, or ``None``. It is kept apart from the message, so ``str(error)``
            stays one sentence about what went wrong.
    """

    def __init__(self, message: str = "", *, hint: str | None = None) -> None:
        """Create the error.

        Args:
            message: What went wrong.
            hint: What to try next.
        """
        super().__init__(message)
        self.hint = hint

    def __reduce__(self) -> tuple[object, ...]:
        """Support ``pickle`` and ``copy`` for subclasses whose constructors take other arguments than the message."""
        return _restore, (type(self), self.args, self.__dict__)


def _restore(kind: type[LogfoldError], args: tuple[object, ...], state: dict[str, object]) -> LogfoldError:
    error = kind.__new__(kind)
    Exception.__init__(error, *args)
    error.__dict__.update(state)
    return error


class ConfigError(LogfoldError, ValueError):
    """An option or configuration value is invalid."""


class FormatError(LogfoldError, ValueError):
    """A log format is invalid, unknown, or could not be detected."""


class SourceError(LogfoldError):
    """An input could not be opened or read."""


class EngineError(LogfoldError, RuntimeError):
    """The engine failed or is unavailable."""


class FormatDetectionError(FormatError):
    """Auto-detection found no built-in format that fits the sampled lines.

    Attributes:
        path: The file that was sampled.
        guesses: The closest formats with their share of matching lines, best first.
    """

    def __init__(self, path: str, guesses: tuple[tuple[str, float], ...]) -> None:
        """Create the error.

        Args:
            path: The file that was sampled.
            guesses: ``(format name, share of matching lines)`` pairs, best first.
        """
        self.path = path
        self.guesses = guesses
        listed = ", ".join(f"{name} ({share:.0%})" for name, share in guesses)
        super().__init__(
            f"could not detect the log format of '{path}' (best guesses: {listed})",
            hint="pass a format explicitly, for example 'plain' or 'regex:<pattern>'",
        )


class _UnknownNameError(LogfoldError):
    """Shared body of the errors for a name that is not registered."""

    def __init__(self, label: str, plural: str, name: str, known: Iterable[str]) -> None:
        self.name = name
        self.known = tuple(sorted(known))
        close = difflib.get_close_matches(name, self.known, n=1)
        super().__init__(
            f"unknown {label} {name!r}; known {plural}: {', '.join(self.known)}",
            hint=f"did you mean {close[0]!r}?" if close else None,
        )


class UnknownFormatError(_UnknownNameError, FormatError):
    """A format name is not registered.

    Attributes:
        name: The name that was asked for.
        known: The registered names, sorted.
    """

    def __init__(self, name: str, known: Iterable[str]) -> None:
        """Create the error.

        Args:
            name: The unknown name.
            known: The registered names.
        """
        super().__init__("format", "formats", name, known)


class UnknownReporterError(_UnknownNameError, ConfigError):
    """A reporter name is not registered.

    Attributes:
        name: The name that was asked for.
        known: The registered names, sorted.
    """

    def __init__(self, name: str, known: Iterable[str]) -> None:
        """Create the error.

        Args:
            name: The unknown name.
            known: The registered names.
        """
        super().__init__("reporter", "reporters", name, known)


class UnknownMatcherError(_UnknownNameError, ConfigError):
    """A diff matcher name is not registered.

    Attributes:
        name: The name that was asked for.
        known: The registered names, sorted.
    """

    def __init__(self, name: str, known: Iterable[str]) -> None:
        """Create the error.

        Args:
            name: The unknown name.
            known: The registered names.
        """
        super().__init__("diff matcher", "matchers", name, known)


_READ_REASONS: tuple[tuple[type[OSError], str], ...] = (
    (FileNotFoundError, "no such file"),
    (PermissionError, "permission denied"),
    (IsADirectoryError, "is a directory"),
    (NotADirectoryError, "not a directory"),
)


def read_error(path: str, error: OSError) -> SourceError:
    """Build the error for an input that could not be opened or read.

    The path is shown as is (not through ``repr``, which doubles backslashes on Windows). The usual failures get a
    fixed English reason, because the operating system's text is localized and repeats the path; any other failure
    keeps the system's text once.

    Args:
        path: The input path.
        error: The failure.

    Returns:
        The error to raise.
    """
    for kind, reason in _READ_REASONS:
        if isinstance(error, kind):
            return SourceError(f"cannot read '{path}': {reason}")
    return SourceError(f"cannot read '{path}': {error.strerror or error}")
