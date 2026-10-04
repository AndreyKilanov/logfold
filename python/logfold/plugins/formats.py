"""Log formats that ship with logfold as default plugins.

A format is data, not code: the engine compiles the description into a fast parser, so a format plugin costs nothing per
line. The objects are registered when :mod:`logfold.plugins` is imported.
"""

from __future__ import annotations

from logfold.ext.formats import JsonFormat, RegexFormat

__all__ = ["LOGFMT", "SERILOG_CLEF"]

LOGFMT = RegexFormat(
    name="logfmt",
    pattern=r"^ts=(?P<ts>\S+) level=(?P<lvl>\w+) (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
)
"""``key=value`` lines: ``ts=2026-10-04T10:00:01Z level=warn msg="slow query" took=412ms``.

The timestamp is ISO-8601. The message is everything after the level, so the remaining ``key=value`` pairs take part
in the template.
"""

SERILOG_CLEF = JsonFormat(
    name="serilog-clef",
    message_keys=("@m", "@mt"),
    time_keys=("@t",),
    level_keys=("@l",),
)
"""Serilog compact JSON (CLEF): ``{"@t": "...", "@m": "User 41 logged in", "@l": "Warning"}``.

``@m`` is the rendered message and ``@mt`` the message template; the first key that is present wins. A line without
``@l`` has no level.
"""
