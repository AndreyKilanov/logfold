"""Declarative log format specifications.

A format plugin does not parse lines itself. It describes the format as data (a :class:`FormatSpec`), and the engine
compiles that description into a fast parser. This keeps plugins simple and keeps Python out of the per-line hot path.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol, Union, runtime_checkable

from logfold.errors import FormatError

SPEC_VERSION = 1


@dataclass(frozen=True, slots=True)
class PlainFormat:
    """Every record is the message.

    Attributes:
        name: Format name.
        record_start: Regular expression that marks the first line of a record. Required with ``multiline``.
        multiline: Join lines that do not start a record to the previous record.
    """

    name: str = "plain"
    record_start: str | None = None
    multiline: bool = False

    def __post_init__(self) -> None:
        """Validate the specification.

        Raises:
            FormatError: If the pattern is invalid or multiline is requested without ``record_start``.
        """
        if self.record_start is not None:
            _check_pattern(self.record_start, "record_start")
        if self.multiline and self.record_start is None:
            raise FormatError("a multiline plain format needs record_start")


@dataclass(frozen=True, slots=True)
class JsonFormat:
    """One JSON object per line.

    Attributes:
        name: Format name.
        message_keys: Candidate keys of the message; the first present key wins.
        time_keys: Candidate keys of the timestamp.
        level_keys: Candidate keys of the level.
        ts_format: ``strptime``-style format of string timestamps; ISO-8601 when ``None``.
    """

    name: str = "jsonl"
    message_keys: tuple[str, ...] = ("message", "msg", "log")
    time_keys: tuple[str, ...] = ("timestamp", "time", "ts", "@timestamp")
    level_keys: tuple[str, ...] = ("level", "severity", "lvl")
    ts_format: str | None = None
    multiline: bool = False

    def __post_init__(self) -> None:
        """Validate the specification.

        Raises:
            FormatError: If no message key is given or multiline is requested.
        """
        if not self.message_keys:
            raise FormatError("a json format needs at least one message key")
        if self.multiline:
            raise FormatError("the json format does not support multiline")


@dataclass(frozen=True, slots=True)
class RegexFormat:
    """A regular expression with named groups.

    The pattern is searched in the first line of a record. Without a message group the whole first line is the
    message.

    Attributes:
        pattern: Regular expression with named groups.
        name: Format name.
        message_group: Group holding the message.
        time_group: Group holding the timestamp text.
        level_group: Group holding the level text.
        ts_format: ``strptime``-style format of the timestamp; ISO-8601 when ``None``.
        multiline: Join lines that do not match ``pattern`` to the previous record.
    """

    pattern: str
    name: str = "regex"
    message_group: str | None = None
    time_group: str | None = None
    level_group: str | None = None
    ts_format: str | None = None
    multiline: bool = False

    def __post_init__(self) -> None:
        """Validate the specification.

        Raises:
            FormatError: If the pattern is invalid or references a missing group.
        """
        compiled = _check_pattern(self.pattern, "pattern")
        for label, group in (("message", self.message_group), ("time", self.time_group), ("level", self.level_group)):
            if group is not None and group not in compiled.groupindex:
                raise FormatError(f"pattern has no named group {group!r} (requested as {label} group)")


FormatSpec = Union[PlainFormat, JsonFormat, RegexFormat]  # noqa: UP007 - runtime alias for isinstance checks


@runtime_checkable
class Format(Protocol):
    """A named source of a :class:`FormatSpec`; plugins implement this or expose a spec directly."""

    name: str

    def spec(self) -> FormatSpec:
        """Return the declarative description of the format."""
        ...


def _check_pattern(pattern: str, what: str) -> re.Pattern[str]:
    try:
        return re.compile(pattern)
    except re.error as error:
        raise FormatError(f"invalid {what} {pattern!r}: {error}") from error


def with_multiline(spec: FormatSpec, multiline: bool) -> FormatSpec:
    """Return ``spec`` with the multiline flag set.

    Args:
        spec: Format specification.
        multiline: Desired flag value.

    Returns:
        A new specification, or ``spec`` itself when nothing changes.

    Raises:
        FormatError: If the format does not support the requested value.
    """
    if spec.multiline == multiline:
        return spec
    if isinstance(spec, PlainFormat):
        return PlainFormat(spec.name, spec.record_start, multiline)
    if isinstance(spec, RegexFormat):
        return RegexFormat(
            spec.pattern,
            spec.name,
            spec.message_group,
            spec.time_group,
            spec.level_group,
            spec.ts_format,
            multiline,
        )
    raise FormatError(f"format {spec.name!r} does not support multiline")
