"""The next step shown under a CLI error, worded for the command line."""

from __future__ import annotations

from logfold.errors import (
    FormatDetectionError,
    UnknownFormatError,
    UnknownMatcherError,
    UnknownReporterError,
)


def _closest_and_listing(error: UnknownFormatError | UnknownReporterError | UnknownMatcherError, listing: str) -> str:
    if error.hint:
        return f"{error.hint} (all of them: '{listing}')"
    return f"run '{listing}' to see the available names"


def hint_for(error: Exception) -> str | None:
    """Return the line that tells the user what to try after ``error``, or ``None``.

    Library errors carry a neutral ``hint``; for the errors a command line user meets most often it is replaced by
    wording that names the options and commands.

    Args:
        error: The error about to be reported.

    Returns:
        The hint without the ``hint:`` label, or ``None`` when there is nothing useful to add.
    """
    if isinstance(error, FormatDetectionError):
        return (
            "pass a format explicitly: -f plain (every line is a message) or -f regex:<pattern>; "
            "'logfold formats' lists the built-in ones"
        )
    if isinstance(error, UnknownFormatError):
        return _closest_and_listing(error, "logfold formats")
    if isinstance(error, UnknownReporterError | UnknownMatcherError):
        return _closest_and_listing(error, "logfold plugins list")
    hint = getattr(error, "hint", None)
    return hint if isinstance(hint, str) else None
