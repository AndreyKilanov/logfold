"""Writing a report to a file, either replacing it or appending to it."""

from __future__ import annotations

import os
from pathlib import Path

from logfold.errors import ConfigError

NOT_APPENDABLE = frozenset({"html", "json", "csv"})
"""Reporters whose output is a whole document (or has a header row), so two of them in one file are not valid."""


def check_appendable(reporter: str) -> None:
    """Refuse to append the output of a reporter that writes a whole document.

    Args:
        reporter: Reporter name.

    Raises:
        ConfigError: If appending its output would produce an invalid file.
    """
    if reporter in NOT_APPENDABLE:
        raise ConfigError(
            f"the {reporter!r} report is a whole document and cannot be appended to a file",
            hint="append text or Markdown reports (--report text or markdown), or write a separate file",
        )


def _separator(path: str | os.PathLike[str]) -> str:
    """Return what must precede appended text: nothing for a new or empty file, otherwise a blank line."""
    try:
        with open(path, "rb") as handle:
            if handle.seek(0, os.SEEK_END) == 0:
                return ""
            handle.seek(-1, os.SEEK_END)
            return "\n" if handle.read(1) == b"\n" else "\n\n"
    except FileNotFoundError:
        return ""


def write_text(path: str | os.PathLike[str], text: str, append: bool = False) -> None:
    """Write UTF-8 text to a file.

    Appended text starts on a new line after a blank line, so that several reports written to one file (for example
    ``$GITHUB_STEP_SUMMARY``, which collects the output of every step) stay separate Markdown sections, and always
    ends with a newline.

    Args:
        path: Destination file.
        text: The text.
        append: Add to the end of the file, creating it when it does not exist, instead of replacing it.

    Raises:
        OSError: If the file cannot be written.
    """
    if not append:
        Path(path).write_text(text, encoding="utf-8")
        return
    if text and not text.endswith("\n"):
        text += "\n"
    separator = _separator(path)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(separator + text)
