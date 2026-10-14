"""Reading a log from ``docker:``, ``kubectl:`` or ``journalctl:`` on the command line."""

from __future__ import annotations

from collections.abc import Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

import logfold
from logfold.api.fetch import DEFAULT_MAX_BYTES, DEFAULT_TIMEOUT, split_source
from logfold.cli.options import PANEL_INPUT
from logfold.cli.runtime import note
from logfold.ext.text import printable

DEFAULT_MAX_MB = DEFAULT_MAX_BYTES >> 20

INPUT_HELP = "Log files forming one run ('-' reads standard input), or sources such as docker:web."

SourceTail = Annotated[
    int | None,
    typer.Option(
        "--source-tail",
        min=1,
        metavar="N",
        help="For a source (docker:, kubectl:, journalctl:), read only the last N lines.",
        rich_help_panel=PANEL_INPUT,
    ),
]
SourceSince = Annotated[
    str | None,
    typer.Option(
        "--source-since",
        metavar="TIME",
        help="For a source, read only what is newer, as 15m or 2026-10-14T10:00:00.",
        rich_help_panel=PANEL_INPUT,
    ),
]
SourcePrevious = Annotated[
    bool,
    typer.Option(
        "--source-previous",
        help="For a kubectl: source, read the previous instance of the container (after a restart).",
        rich_help_panel=PANEL_INPUT,
    ),
]
SourceTimeout = Annotated[
    float,
    typer.Option(
        "--source-timeout",
        min=1,
        metavar="SECONDS",
        help="For a source, stop the program after this time.",
        rich_help_panel=PANEL_INPUT,
    ),
]
SourceMaxMb = Annotated[
    int,
    typer.Option(
        "--source-max-mb",
        min=1,
        metavar="MB",
        help="For a source, fail when the program prints more than this.",
        rich_help_panel=PANEL_INPUT,
    ),
]


@dataclass(frozen=True)
class SourceArgs:
    """The ``--source-*`` options of a command."""

    tail: int | None = None
    since: str | None = None
    previous: bool = False
    timeout: float = DEFAULT_TIMEOUT
    max_mb: int = DEFAULT_MAX_MB


def open_inputs(stack: ExitStack, inputs: Sequence[str], args: SourceArgs, quiet: bool) -> list[str]:
    """Turn the sources among the inputs into temporary files that live as long as ``stack``.

    Args:
        stack: Closed by the command when it ends; it removes the temporary files.
        inputs: Paths, ``-``, and sources such as ``docker:web``.
        args: The ``--source-*`` options.
        quiet: Whether ``--quiet`` was given.

    Returns:
        The inputs with every source replaced by the path of its file.

    Raises:
        ConfigError: If a ``--source-*`` option is given but no input is a source.
        LogfoldError: If a source cannot be read (see :func:`logfold.fetch`).
    """
    paths: list[str] = []
    used = False
    for text in inputs:
        if split_source(text) is None:
            paths.append(text)
            continue
        if Path(text).exists():
            raise logfold.ConfigError(
                f"{printable(text)!r} is both a file in this folder and a source",
                hint=f"write ./{printable(text)} for the file, or rename it",
            )
        used = True
        path = stack.enter_context(
            logfold.fetch(
                text,
                tail=args.tail,
                since=args.since,
                previous=args.previous,
                timeout=args.timeout,
                max_bytes=args.max_mb << 20,
            )
        )
        note(f"read {path.stat().st_size / (1 << 20):.1f} MiB from {printable(text)}", quiet)
        paths.append(str(path))
    if not used and (args.tail or args.since or args.previous):
        raise logfold.ConfigError(
            "--source-tail, --source-since and --source-previous need a source such as docker:web"
        )
    return paths
