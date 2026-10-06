"""Neutralizing text from a log for the targets of the CI and notification reporters.

Log lines are untrusted input. Each helper returns one line of visible characters: control characters (terminal escape
sequences) are shown as hex escapes by :func:`logfold.ext.printable`, and what the target format treats as markup
is made inert on top of that.
"""

from __future__ import annotations

import re
from datetime import datetime

from logfold.ext.text import printable

__all__ = [
    "alert_noun",
    "clip",
    "code_span",
    "defuse_mentions",
    "int_option",
    "iso",
    "label_value",
    "run_names",
    "xml_text",
]

_BACKSLASH = chr(92)
_MENTION = re.compile(r"<(?=[!@#])|@(?=(?:channel|here|everyone|all)\b)", re.IGNORECASE)
_XML_INVALID = re.compile(
    "[^"
    + chr(9)
    + chr(10)
    + chr(13)
    + chr(0x20)
    + "-"
    + chr(0xD7FF)
    + chr(0xE000)
    + "-"
    + chr(0xFFFD)
    + chr(0x10000)
    + "-"
    + chr(0x10FFFF)
    + "]"
)


def int_option(options: dict[str, object], name: str, default: int, *, minimum: int = 1) -> int:
    """Read a whole-number reporter option, falling back to the default for anything else.

    Args:
        options: The keyword options given to ``render``.
        name: Option name.
        default: Value used when the option is missing, not an integer or below ``minimum``.
        minimum: Smallest accepted value.

    Returns:
        The option value or the default.
    """
    value = options.get(name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= minimum else default


def clip(text: str, width: int, *, tail: bool = False) -> str:
    """Make text one printable line and cut it to ``width`` characters.

    Args:
        text: Text that may span lines and hold control characters.
        width: Longest result, counting the three dots that mark a cut.
        tail: Keep the end of a long text instead of the start (the file name at the end of a path).

    Returns:
        The text with whitespace runs collapsed to single spaces.
    """
    flat = " ".join(printable(text).split())
    if len(flat) <= width:
        return flat
    return "..." + flat[3 - width :] if tail else flat[: width - 3] + "..."


def defuse_mentions(text: str) -> str:
    """Break the mention syntax of chat systems with a zero-width space, so that a log line cannot ping a channel.

    Slack reads ``<!here>``, ``<@U123>`` and ``<#C123>`` and Mattermost reads ``@channel``, ``@here``, ``@all`` and
    ``@everyone``. A code span is not enough for every client and every way of posting, so the characters that start
    them are separated from what follows; the text looks the same.

    Args:
        text: Text from a log.

    Returns:
        The text with a zero-width space after ``<`` before ``!``, ``@`` or ``#`` and after ``@`` before a group name.
    """
    return _MENTION.sub(lambda found: found.group() + chr(0x200B), text)


def code_span(text: str, width: int, *, tail: bool = False) -> str:
    """Return text as a Markdown code span that cannot be closed from inside.

    Markdown does not interpret HTML, links, mentions or emphasis inside a code span, which is what keeps a hostile
    log line from pinging a channel or injecting markup into a job summary.

    Args:
        text: Text from a log.
        width: Longest text before the ellipsis.
        tail: Keep the end of a long text instead of the start.

    Returns:
        The text between backticks, with backticks inside it replaced by apostrophes.
    """
    return "`" + clip(text, width, tail=tail).replace("`", "'") + "`"


def run_names(before: str, after: str, width: int) -> str:
    """Return ``before -> after`` as two code spans that keep the end of a long path, where the file name is."""
    first = code_span(defuse_mentions(before), width, tail=True)
    second = code_span(defuse_mentions(after), width, tail=True)
    return f"{first} -> {second}"


def xml_text(text: str, width: int, *, tail: bool = False) -> str:
    """Return text for an XML 1.0 attribute or element: one line, no character that XML forbids.

    Escaping ``&``, ``<``, ``>`` and quotes is left to the XML writer; this removes what no escaping can express, such
    as control characters and the non-characters U+FFFE and U+FFFF, by showing them as ``U+XXXX``.

    Args:
        text: Text from a log.
        width: Longest text before the ellipsis.
        tail: Keep the end of a long text instead of the start.

    Returns:
        The cleaned line.
    """
    return _XML_INVALID.sub(lambda found: f"U+{ord(found.group()):04X}", clip(text, width, tail=tail))


def label_value(text: str, width: int) -> str:
    """Return text escaped for a double-quoted Prometheus label value.

    Args:
        text: Text from a log.
        width: Longest text before the ellipsis.

    Returns:
        The line with backslashes and double quotes escaped; it holds no line feed.
    """
    return clip(text, width).replace(_BACKSLASH, _BACKSLASH * 2).replace('"', _BACKSLASH + '"')


def iso(value: datetime | None) -> str:
    """Return a moment as ISO 8601 text, or an empty string when there is none."""
    return value.isoformat() if value is not None else ""


def alert_noun(count: int) -> str:
    """Return ``1 new WARN+ template`` or ``3 new WARN+ templates``."""
    return f"{count:,} new WARN+ template" + ("" if count == 1 else "s")
