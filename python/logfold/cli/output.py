"""Choosing the reporters of a command: the ``--out`` suffix, ``--report NAME`` and ``--json``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from logfold.errors import ConfigError, LogfoldError
from logfold.ext import registry
from logfold.model import AnalysisResult, DiffResult

SUFFIX_REPORTERS = {
    ".html": "html",
    ".htm": "html",
    ".json": "json",
    ".txt": "text",
    ".md": "markdown",
    ".csv": "csv",
}


@dataclass(frozen=True, slots=True)
class Outputs:
    """The reporters a command uses.

    Attributes:
        file: Reporter that writes the ``--out`` file, or ``None`` without ``--out``.
        stdout: Reporter whose text replaces the tables on standard output, or ``None`` to print the tables.
    """

    file: str | None
    stdout: str | None


def _checked(name: str, kind: str) -> str:
    reporter = registry.get_reporter(name)
    if kind not in reporter.kinds:
        raise ConfigError(f"reporter {name!r} does not support {kind} results")
    return name


def resolve_outputs(kind: str, out: Path | None, report: str | None, as_json: bool) -> Outputs:
    """Decide which reporters a command runs, before any log is read.

    ``--report NAME`` names the reporter explicitly: it writes the ``--out`` file when there is one and is printed
    instead of the tables otherwise. Without it the ``--out`` suffix selects the reporter and ``--json`` prints JSON.

    Args:
        kind: ``analysis`` or ``diff``.
        out: The ``--out`` file, if any.
        report: The ``--report`` name, if any.
        as_json: Whether ``--json`` was given.

    Returns:
        The reporters for the file and for standard output.

    Raises:
        ConfigError: If the options contradict each other, the suffix is unknown, or the reporter is unknown or does
            not support ``kind``.
    """
    if as_json and report is not None:
        raise ConfigError("--json and --report cannot be combined; use --report json")
    stdout = "json" if as_json else None
    file: str | None = None
    if report is not None:
        name = _checked(report, kind)
        if out is None:
            stdout = name
        else:
            file = name
    elif out is not None:
        suffix = out.suffix.lower()
        mapped = SUFFIX_REPORTERS.get(suffix)
        if mapped is None:
            known = ", ".join(sorted(SUFFIX_REPORTERS))
            reason = f"the suffix {out.suffix!r} is not known" if out.suffix else "it has no suffix"
            raise ConfigError(
                f"cannot choose a report format for '{out}': {reason}",
                hint=f"end the name with one of {known}, or name the reporter with --report NAME "
                "('logfold plugins list' shows them)",
            )
        file = _checked(mapped, kind)
    return Outputs(file=file, stdout=stdout)


_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def printable(text: str) -> str:
    r"""Make text safe to print on a terminal by showing control characters instead of acting on them.

    Log content is untrusted: an escape sequence in a message could retitle the window, hide text or write to the
    clipboard. Tabs and line feeds are kept; every other control character becomes a visible ``\xNN`` escape.

    Args:
        text: Text that may contain control characters.

    Returns:
        The text with control characters replaced.
    """
    return _CONTROL.sub(lambda found: f"\\x{ord(found.group()):02x}", text)


def render_report(result: AnalysisResult | DiffResult, reporter: str, top: int | None = None) -> str:
    """Render a result with a named reporter, turning a failing reporter into a clean error.

    Args:
        result: The result.
        reporter: Reporter name.
        top: Rows of the ``text`` reporter; other reporters keep their own limits.

    Returns:
        The rendered text.

    Raises:
        ConfigError: If the reporter raises or returns something other than text.
    """
    try:
        text = result.render(reporter, top=top) if reporter == "text" and top is not None else result.render(reporter)
    except LogfoldError:
        raise
    except Exception as error:
        raise ConfigError(f"reporter {reporter!r} failed: {error}") from error
    if not isinstance(text, str):
        raise ConfigError(f"reporter {reporter!r} returned {type(text).__name__}, expected text")
    return text
