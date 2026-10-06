"""Choosing the reporters of a command: the ``--out`` suffix, ``--report NAME`` and ``--json``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from logfold.errors import ConfigError, LogfoldError
from logfold.ext import registry
from logfold.ext.files import check_appendable
from logfold.model import AnalysisResult, DiffResult


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


def resolve_outputs(kind: str, out: Path | None, report: str | None, as_json: bool, append: bool = False) -> Outputs:
    """Decide which reporters a command runs, before any log is read.

    ``--report NAME`` names the reporter explicitly: it writes the ``--out`` file when there is one and is printed
    instead of the tables otherwise. Without it the ``--out`` suffix selects the reporter and ``--json`` prints JSON.

    Args:
        kind: ``analysis`` or ``diff``.
        out: The ``--out`` file, if any.
        report: The ``--report`` name, if any.
        as_json: Whether ``--json`` was given.
        append: Whether ``--append`` was given.

    Returns:
        The reporters for the file and for standard output.

    Raises:
        ConfigError: If the options contradict each other, the suffix is unknown, or the reporter is unknown or does
            not support ``kind``, or ``--append`` has no ``--out`` or names a report that cannot be appended.
    """
    if append and out is None:
        raise ConfigError("--append needs --out")
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
        mapped = registry.reporter_for_suffix(out)
        file = _checked(mapped, kind)
    if append and file is not None:
        check_appendable(file)
    return Outputs(file=file, stdout=stdout)


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
