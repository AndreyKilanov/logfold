"""Log formats of servers, databases, containers and CI that ship with logfold as default plugins.

Like :mod:`logfold.plugins.formats`, they are data: the engine compiles each description into a parser. None of them is
picked by ``--format auto``; name one with ``--format``.
"""

from __future__ import annotations

from logfold.ext.formats import JsonFormat, RegexFormat
from logfold.ext.log4j import LOG4J_DEFAULT_PATTERN, log4j_format

__all__ = ["DOCKER_JSON", "GITHUB_ACTIONS", "HAPROXY", "LOG4J", "POSTGRESQL", "POSTGRESQL_CSV"]

HAPROXY = RegexFormat(
    name="haproxy",
    pattern=(
        r"^(?:[^\[\]]*haproxy\[\d+\]: )?\S+:\d+ \[(?P<ts>\d{2}/[A-Za-z]{3}/\d{4}:\d{2}:\d{2}:\d{2}\.\d+)\] "
        r"(?P<msg>\S+ \S+ .*)$"
    ),
    message_group="msg",
    time_group="ts",
    ts_format="%d/%b/%Y:%H:%M:%S.%f",
)
"""HAProxy HTTP and TCP logs (``option httplog`` and ``option tcplog``), with or without the syslog prefix.

The message runs from the frontend to the end of the line: ``fe_http be_app/srv1 0/0/1/12/13 200 1534 - - ---- 3/3/0/0/0
0/0 "GET /index.html HTTP/1.1"``. The termination state (``----``, ``sH--``) stays in the template, so a change in how
requests end shows up in ``diff``. The accept time has no zone.
"""

_PG_TIME = r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}(?:\.\d+)?"
_PG_LEVEL = r"LOG|STATEMENT|DETAIL|HINT|CONTEXT|QUERY|LOCATION|ERROR|FATAL|PANIC|WARNING|NOTICE|INFO|DEBUG[1-5]?"
_CSV_FIELD = r'(?:"(?:[^"]|"")*"|[^,"]*)'

POSTGRESQL = RegexFormat(
    name="postgresql",
    pattern=(
        rf"^(?P<ts>{_PG_TIME})(?: (?:[A-Z]{{2,5}}|[+-]\d{{2}}(?::?\d{{2}})?))?[ :].{{0,120}}?[ \t\]:]"
        rf"(?P<lvl>{_PG_LEVEL}):  (?P<msg>.*)$"
    ),
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    multiline=True,
)
"""PostgreSQL server log in the ``stderr`` destination.

A line looks like ``2026-10-06 12:00:00.123 UTC [1234] ERROR:  deadlock detected``.

Any ``log_line_prefix`` that starts with a timestamp works (``%m``, ``%t``, and prefixes with ``user@db`` or an
address). ``DETAIL``, ``HINT`` and ``STATEMENT`` lines are records of their own; tab-indented continuation lines of a
statement join the record. ``LOG`` and the ``DEBUG`` levels carry no logfold level. The timestamp's zone name is
ignored.
"""

POSTGRESQL_CSV = RegexFormat(
    name="postgresql-csv",
    pattern=(
        rf'^(?P<ts>{_PG_TIME})(?: [A-Z]{{2,5}})?,(?:{_CSV_FIELD},){{10}}(?P<lvl>[A-Z]+[0-9]?),[^,"]*,'
        r'"(?P<msg>(?:[^"]|"")*)'
    ),
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    multiline=True,
)
"""PostgreSQL ``csvlog``: the severity is the 12th column and the message the 14th.

A message that spans several lines is read up to the end of its first line; the other lines join the record. Doubled
quotes inside the message stay as they are.
"""

DOCKER_JSON = JsonFormat(name="docker-json", message_keys=("log",), time_keys=("time",), level_keys=())
"""Docker ``json-file`` driver.

A line looks like ``{"log":"user 41 logged in\\n","stream":"stdout","time":"2026-10-06T12:00:00.123456789Z"}``.

The line break at the end of ``log`` is dropped; the stream is not a level.
"""

GITHUB_ACTIONS = RegexFormat(
    name="github-actions",
    pattern=(
        r"^\ufeff?(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z) "
        r"(?:##\[(?P<lvl>error|warning|notice|debug)\])?(?P<msg>.*)$"
    ),
    message_group="msg",
    time_group="ts",
    level_group="lvl",
)
"""GitHub Actions job logs (the text of a downloaded run): ``2026-10-06T12:00:03.1234567Z ##[error]Process completed``.

A leading ``##[error]``, ``##[warning]``, ``##[notice]`` or ``##[debug]`` is read as the level and left out of the
message; the other commands (``##[group]``, ``##[endgroup]``, ``##[command]``) stay in the message. A byte-order mark
in front of the first line is accepted.
"""

LOG4J = log4j_format(LOG4J_DEFAULT_PATTERN, name="log4j")
"""log4j and logback output in the pattern ``%d{ISO8601} %-5p [%t] %c - %m%n``; stack traces join their record.

For another pattern use ``--format "log4j:<pattern>"``.
"""
