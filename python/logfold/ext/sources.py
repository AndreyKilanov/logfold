"""Source extension point: names the program that prints the log of a container, a pod or a service.

A source only builds the argument list. Running it is the job of :func:`logfold.fetch`, which looks the program up,
starts it without a shell, bounds its time and output, and removes the temporary file, so a plugin cannot get any of
that wrong.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from logfold.errors import ConfigError

_VALUE = re.compile(r"[0-9A-Za-z][0-9A-Za-z:.+_ -]{0,63}")


@dataclass(frozen=True)
class SourceOptions:
    """What to read from a source, apart from its target.

    Attributes:
        tail: Only the last this many lines, or ``None`` for all of them.
        since: Only what is newer than this, in the form the program accepts (``15m``, ``2026-10-14T10:00:00``), or
            ``None``.
        previous: The previous instance of the target, for a restarted container (``kubectl`` only).
    """

    tail: int | None = None
    since: str | None = None
    previous: bool = False

    def __post_init__(self) -> None:
        """Check the values, which end up as program arguments.

        Raises:
            ConfigError: If ``tail`` is not positive or ``since`` is not a short time or duration.
        """
        if self.tail is not None and self.tail < 1:
            raise ConfigError(f"tail must be at least 1, got {self.tail}")
        if self.since is not None and not _VALUE.fullmatch(self.since):
            raise ConfigError(
                f"since must be a duration or a time such as 15m or 2026-10-14T10:00:00, got {self.since!r}"
            )


@dataclass(frozen=True)
class Command:
    """The program to run and its arguments.

    Attributes:
        argv: The program name without a folder (it is looked up on ``PATH``), then its arguments. Every item is a
            non-empty string without a NUL character.
        merge_stderr: Read the standard error of the program as part of the log (``docker logs`` prints the error
            stream of the container there), instead of keeping it for error messages.
    """

    argv: tuple[str, ...]
    merge_stderr: bool = False

    def __post_init__(self) -> None:
        """Check the argument list.

        Raises:
            ConfigError: If it is empty, names a folder, or holds an item that is empty or has a NUL character.
        """
        if not self.argv or any(not isinstance(item, str) or not item or "\0" in item for item in self.argv):
            raise ConfigError("a source command needs non-empty arguments without NUL characters")
        if "/" in self.argv[0] or "\\" in self.argv[0]:
            raise ConfigError(f"a source runs a program found on PATH, not a path: {self.argv[0]!r}")


@runtime_checkable
class Source(Protocol):
    """A program that prints a log, and the way to ask it for one target.

    Attributes:
        name: Name used before the colon in ``docker:web``.
        description: One line for people.
        platforms: ``sys.platform`` prefixes the source works on (``("linux",)``); empty means everywhere.
    """

    name: str
    description: str
    platforms: tuple[str, ...]

    def command(self, target: str, options: SourceOptions) -> Command:
        """Return the command that prints the log of ``target``.

        The target comes from the user and is untrusted: check it against a narrow pattern, never let it start with
        ``-``, and put it after ``--`` where the program understands that. The command must only read, and must not
        follow the log (a program that never ends is cut off by the time limit).

        Args:
            target: What follows the colon in the source text.
            options: What to read.

        Returns:
            The command to run.

        Raises:
            ConfigError: If the target or an option is not valid for this source.
        """
        ...
