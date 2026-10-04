"""Built-in log formats, auto-detection and format resolution."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from logfold.errors import FormatError
from logfold.ext import registry
from logfold.ext.formats import Format, FormatSpec, RegexFormat, with_multiline
from logfold.formats.auto import Detection, detect_format
from logfold.formats.builtin import BUILTIN_FORMATS, register_builtin_formats

register_builtin_formats()

_MESSAGE_GROUPS = ("message", "msg")
_TIME_GROUPS = ("timestamp", "time", "ts")
_LEVEL_GROUPS = ("level", "lvl", "severity")


def regex_format_from_pattern(pattern: str) -> RegexFormat:
    """Build a regex format picking conventional group names (``message``/``msg``, ``timestamp``/``ts``, ``level``).

    Args:
        pattern: Regular expression with named groups.

    Returns:
        The format specification.
    """
    try:
        groups = re.compile(pattern).groupindex
    except re.error as error:
        raise FormatError(f"invalid regex format {pattern!r}: {error}") from error

    def pick(candidates: tuple[str, ...]) -> str | None:
        return next((name for name in candidates if name in groups), None)

    return RegexFormat(
        pattern=pattern,
        message_group=pick(_MESSAGE_GROUPS),
        time_group=pick(_TIME_GROUPS),
        level_group=pick(_LEVEL_GROUPS),
    )


@dataclass(frozen=True, slots=True)
class ResolvedFormat:
    """A resolved format.

    Attributes:
        spec: The specification to mine with.
        confidence: Detection confidence, ``None`` unless the format was auto-detected.
        multiline_auto: True when multiline was switched on because the sample looked multiline.
    """

    spec: FormatSpec
    confidence: float | None = None
    multiline_auto: bool = False


def resolve_format(
    fmt: str | FormatSpec | Format, paths: Sequence[str], multiline: bool | None = None
) -> ResolvedFormat:
    """Turn a user supplied format into a specification.

    Args:
        fmt: A registered name, ``auto``, ``regex:<pattern>``, a specification or a ``Format`` object.
        paths: Input paths of the first run (used by ``auto``).
        multiline: Override of the multiline flag; ``None`` keeps the format's own setting (and lets auto-detection
            switch multiline on when indented continuation lines are found).

    Returns:
        The resolved format.
    """
    confidence: float | None = None
    hint = False
    if isinstance(fmt, str):
        if fmt == "auto":
            detection = detect_format(paths)
            spec, confidence, hint = detection.spec, detection.confidence, detection.multiline_hint
        elif fmt.startswith("regex:"):
            spec = regex_format_from_pattern(fmt[len("regex:") :])
        else:
            spec = registry.get_format(fmt)
    elif isinstance(fmt, Format):
        spec = fmt.spec()
    else:
        spec = fmt
    auto = False
    if multiline is not None:
        spec = with_multiline(spec, multiline)
    elif hint and not spec.multiline:
        try:
            spec = with_multiline(spec, True)
            auto = True
        except FormatError:
            auto = False
    return ResolvedFormat(spec, confidence, auto)


__all__ = [
    "BUILTIN_FORMATS",
    "Detection",
    "ResolvedFormat",
    "detect_format",
    "regex_format_from_pattern",
    "resolve_format",
]
