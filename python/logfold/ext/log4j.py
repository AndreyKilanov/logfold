"""Turn a log4j or logback conversion pattern into a regex format.

``%d{HH:mm:ss.SSS} [%t] %-5p %c - %m%n`` describes how a line is laid out; :func:`log4j_format` compiles that
description into a :class:`~logfold.ext.formats.RegexFormat`, so the engine parses the log as fast as any other regex
format.
"""

from __future__ import annotations

import re

from logfold.errors import FormatError
from logfold.ext.formats import RegexFormat

__all__ = ["LOG4J_DEFAULT_PATTERN", "log4j_format"]

LOG4J_DEFAULT_PATTERN = "%d{ISO8601} %-5p [%t] %c - %m%n"
"""The pattern behind the registered ``log4j`` format."""

_SPECIFIER = re.compile(r"%(?P<left>-?)(?P<min>\d*)(?:\.(?P<max>-?\d+))?(?P<rest>[A-Za-z]*)")
_OPTION = re.compile(r"\{([^}]*)\}")

_DATE = frozenset({"d", "date"})
_LEVEL = frozenset({"p", "level", "priority"})
_MESSAGE = frozenset({"m", "msg", "message"})
_TOKEN = frozenset(
    {"c", "logger", "C", "class", "F", "file", "M", "method", "l", "location", "L", "line", "r", "relative"}
    | {"pid", "processId", "T", "tid", "threadId", "threadPriority", "tp", "sn", "sequenceNumber"}
)
_FREE = frozenset(
    {"t", "thread", "threadName", "tn", "x", "NDC", "X", "mdc", "MDC", "marker", "markerSimpleName", "K", "map", "MAP"}
    | {"u", "uuid", "hostName", "hostname", "host", "N", "nano", "nanoTime"}
)
_THROWABLE = frozenset(
    {"ex", "exception", "throwable", "xEx", "xException", "xThrowable", "rEx", "rException", "rThrowable"}
    | {"wEx", "wException", "wThrowable", "xwEx"}
)
_WORDS = _DATE | _LEVEL | _MESSAGE | _TOKEN | _FREE | _THROWABLE | {"n"}

_NAMED_DATES = {
    "ISO8601": (r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[,.]\d+", None),
    "ISO8601_BASIC": (r"\d{8}T\d{6}[,.]\d+", "%Y%m%dT%H%M%S,%f"),
    "ABSOLUTE": (r"\d{2}:\d{2}:\d{2}[,.]\d+", "%H:%M:%S,%f"),
    "DATE": (r"\d{2} [A-Za-z]{3} \d{4} \d{2}:\d{2}:\d{2}[,.]\d+", "%d %b %Y %H:%M:%S,%f"),
}

_JAVA_FIELDS = {
    "yyyy": (r"\d{4}", "%Y"),
    "yy": (r"\d{2}", "%y"),
    "MM": (r"\d{2}", "%m"),
    "M": (r"\d{1,2}", "%m"),
    "MMM": (r"[A-Za-z]{3}", "%b"),
    "MMMM": (r"[A-Za-z]+", "%B"),
    "dd": (r"\d{2}", "%d"),
    "d": (r"\d{1,2}", "%d"),
    "HH": (r"\d{2}", "%H"),
    "H": (r"\d{1,2}", "%H"),
    "mm": (r"\d{2}", "%M"),
    "m": (r"\d{1,2}", "%M"),
    "ss": (r"\d{2}", "%S"),
    "s": (r"\d{1,2}", "%S"),
    "DDD": (r"\d{3}", "%j"),
}
_ZONE = (r"(?:Z|[+-]\d{2}(?::?\d{2})?)", "%z")
_REGEX_SPECIAL = frozenset("\\.^$|?*+()[]{}")


def log4j_format(pattern: str, *, name: str = "log4j", multiline: bool = True) -> RegexFormat:
    """Build a regex format from a log4j, log4j2 or logback conversion pattern.

    Understood: ``%d`` (``ISO8601``, ``ABSOLUTE``, ``DATE`` or a Java date pattern with the usual letters, ``X``/``Z``
    for an offset), ``%p``/``%level``, ``%m``/``%msg``, ``%c``/``%logger``, ``%t``/``%thread``, the other plain fields
    (``%C``, ``%F``, ``%L``, ``%M``, ``%r``, ``%X{key}``, ``%x``, ...), ``%ex`` and its relatives (the stack trace is
    printed on the following lines, which join the record), ``%%`` and a trailing ``%n``. Width and ``-`` modifiers
    (``%-5p``, ``%5.5p``) are honoured as padding.

    Args:
        pattern: The conversion pattern.
        name: Name of the format.
        multiline: Join lines that do not start a record (stack traces) to the previous record.

    Returns:
        The format specification.

    Raises:
        FormatError: If the pattern uses a converter that is not supported, or a date pattern that cannot be read.
    """
    parts: list[str] = []
    state = _State()
    index = 0
    text = pattern
    while index < len(text):
        char = text[index]
        if char != "%" or text.startswith("%%", index):
            parts.append(_literal(char))
            state.last_was_message = False
            index += 1 if char != "%" else 2
            continue
        match = _SPECIFIER.match(text, index)
        word = _longest_word(match.group("rest")) if match else ""
        if match is None or not word:
            raise _unsupported("%" + (match.group("rest") if match else ""), pattern)
        index = match.start("rest") + len(word)
        options: list[str] = []
        while (option := _OPTION.match(text, index)) is not None:
            options.append(option.group(1))
            index = option.end()
        if word == "n" and index >= len(text):
            continue
        if word == "n":
            raise FormatError(f"a newline inside the pattern {pattern!r} is not supported: one record is one line")
        field = _field(word, options, state, pattern)
        if field and match.group("min"):
            field = field + " *" if match.group("left") else " *" + field
        parts.append(field)
    body = "".join(parts)
    if not body:
        raise FormatError(f"the pattern {pattern!r} has no fields", hint="a pattern needs at least %m or %d")
    anchor = "$" if state.last_was_message else ""
    return RegexFormat(
        pattern=f"^{body}{anchor}",
        name=name,
        message_group="msg" if state.message else None,
        time_group="ts" if state.time else None,
        level_group="lvl" if state.level else None,
        ts_format=state.ts_format,
        multiline=multiline,
    )


class _State:
    def __init__(self) -> None:
        self.time = False
        self.level = False
        self.message = False
        self.last_was_message = False
        self.ts_format: str | None = None


def _field(word: str, options: list[str], state: _State, pattern: str) -> str:
    if word in _THROWABLE:
        return ""
    state.last_was_message = False
    if word in _DATE and not state.time:
        state.time = True
        regex, state.ts_format = _date(options[0] if options else "ISO8601", pattern)
        return f"(?P<ts>{regex})"
    if word in _LEVEL and not state.level:
        state.level = True
        return r"(?P<lvl>[A-Za-z]+)"
    if word in _MESSAGE and not state.message:
        state.message = True
        state.last_was_message = True
        return "(?P<msg>.*)"
    if word in _TOKEN or word in _DATE or word in _LEVEL:
        return r"\S+"
    if word in _MESSAGE or word in _FREE:
        return ".*?"
    raise _unsupported(f"%{word}", pattern)


def _date(spec: str, pattern: str) -> tuple[str, str | None]:
    named = _NAMED_DATES.get(spec)
    if named is not None:
        return named
    regex: list[str] = []
    ts_format: list[str] = []
    index = 0
    while index < len(spec):
        char = spec[index]
        if char == "'":
            end = spec.find("'", index + 1)
            if end < 0:
                raise FormatError(f"unterminated quote in the date pattern {spec!r} of {pattern!r}")
            literal = spec[index + 1 : end] or "'"
            regex.extend(_literal(c) for c in literal)
            ts_format.append(literal.replace("%", "%%"))
            index = end + 1
        elif char.isalpha():
            rest = spec[index:]
            chars = rest[: len(rest) - len(rest.lstrip(char))]
            index += len(chars)
            field = _date_field(char, chars, spec, pattern)
            regex.append(field[0])
            ts_format.append(field[1])
        else:
            regex.append(_literal(char))
            ts_format.append(char.replace("%", "%%"))
            index += 1
    return "".join(regex), "".join(ts_format)


def _date_field(char: str, chars: str, spec: str, pattern: str) -> tuple[str, str]:
    if char == "S":
        return r"\d{1,9}", "%f"
    if char in "XxZ":
        return _ZONE
    found = _JAVA_FIELDS.get(chars)
    if found is None:
        raise FormatError(
            f"the date letter {chars!r} in {spec!r} (pattern {pattern!r}) is not supported",
            hint="use letters y M d H m s S X Z, ISO8601 or ABSOLUTE, or write the format as regex:<pattern>",
        )
    return found


def _longest_word(letters: str) -> str:
    for end in range(len(letters), 0, -1):
        if letters[:end] in _WORDS:
            return letters[:end]
    return ""


def _literal(char: str) -> str:
    return "\\" + char if char in _REGEX_SPECIAL else char


def _unsupported(what: str, pattern: str) -> FormatError:
    return FormatError(
        f"the converter {what!r} of the pattern {pattern!r} is not supported",
        hint="supported: %d %p %m %c %t %C %F %L %M %r %X %x %ex %n and %%; for anything else use regex:<pattern>",
    )
