"""Helpers for text that comes from logs, which are untrusted input."""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def printable(text: str) -> str:
    r"""Make text safe to print on a terminal by showing control characters instead of acting on them.

    Log content is untrusted: an escape sequence in a message could retitle the window, hide text or write to the
    clipboard. Tabs and line feeds are kept; every other control character (C0, DEL and C1) becomes a visible ``\xNN``
    escape. Reporters that produce text for people should pass every value taken from a log through this function.

    Args:
        text: Text that may contain control characters.

    Returns:
        The text with control characters replaced.
    """
    return _CONTROL.sub(lambda found: f"\\x{ord(found.group()):02x}", text)
