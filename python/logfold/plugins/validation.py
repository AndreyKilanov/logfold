"""What each built-in format was checked on, and what it was not.

One place for the facts that ``logfold plugins info NAME`` prints and that the table in ``docs/guide.md`` shows. The
long account, with the numbers and what each check found, is ``bench/docs/FORMAT_VALIDATION.md``; a test keeps the
three in step. A text here says what a check compared the format with (a real program, logs of other projects, damaged
logs); it is not a promise that the format reads every log of that program.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

__all__ = ["CHECKS", "FormatChecks", "format_checks", "markdown_table"]

FUZZED = (
    "Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); "
    "the chunking never changes the result."
)


@dataclass(frozen=True, slots=True)
class FormatChecks:
    """What a format was checked on.

    Attributes:
        checked: What it was compared with, with versions and counts. No ``|`` (the text goes into a table).
        not_checked: What was not tried, and the limits that were found.
    """

    checked: str
    not_checked: str


CHECKS: dict[str, FormatChecks] = {
    "plain": FormatChecks(
        "Nothing to compare with: every line is a record. " + FUZZED,
        "Nothing format specific.",
    ),
    "nginx": FormatChecks(
        "Test logs of Filebeat's nginx module, 3 of 3 read as the project expects (a host in front, a chain of "
        "proxies); a generated 100 MB log for speed. Picked by -f auto. " + FUZZED,
        "A real nginx process; a log_format other than the combined one.",
    ),
    "apache": FormatChecks(
        "Test logs of Filebeat's apache module, 4 of 5 (combined and vhost_combined). Picked by -f auto (as nginx, "
        "the pattern is the same). " + FUZZED,
        "A real Apache process; a custom LogFormat such as ssl_request_log (the time is not first: use regex:PATTERN).",
    ),
    "nginx-error": FormatChecks(
        "Filebeat's nginx error test log, 1 of 1 (PHP warnings that continue an entry are joined). " + FUZZED,
        "More than one sample; a real nginx process. Not picked by -f auto on that sample.",
    ),
    "syslog": FormatChecks(
        "Filebeat's system syslog and auth logs, 7 of 7 (classic time, rsyslog's ISO time, macOS continuation lines); "
        "the Linux, Mac and OpenSSH sets of Loghub are picked as syslog by -f auto. " + FUZZED,
        "A real syslog daemon; RFC 5424 lines. The classic time has no year (it reads as 1970).",
    ),
    "k8s": FormatChecks(
        "One Filebeat sample of the CRI format, 1 of 1. Picked by -f auto. " + FUZZED,
        "A real containerd or CRI-O; more samples.",
    ),
    "journald": FormatChecks(
        FUZZED,
        "Real journalctl -o json output (Filebeat's samples are the export format, not JSON).",
    ),
    "jsonl": FormatChecks(
        "Filebeat's samples of Elasticsearch, Logstash and MongoDB JSON logs, 8 of 14; inputs of Fluent Bit's "
        "Docker mode. Picked by -f auto. " + FUZZED,
        "An object over several lines; a message that is not at the top level (log4j2's JsonLayout, Elasticsearch's "
        "slowlog); a time that is an object (MongoDB: records without time and level).",
    ),
    "app": FormatChecks(
        "Generated logs and the Hadoop set of Loghub (picked by -f auto, 2 of 2). " + FUZZED,
        "A program that writes exactly this shape: for Java logging use log4j:PATTERN, which was checked.",
    ),
    "logfmt": FormatChecks(
        "Loki's test logs, 2 of 2 (Go services, other pairs before level). " + FUZZED,
        "Real Go programs and logrus; not picked by -f auto.",
    ),
    "serilog-clef": FormatChecks(
        FUZZED,
        "Real Serilog output or samples of other projects; not picked by -f auto.",
    ),
    "haproxy": FormatChecks(
        "Real HAProxy 2.8.30, 3.0.29 and 3.2.25 in Docker, the five forms of log stdout format, every record compared "
        "with the requests that were sent; Filebeat's HAProxy samples, 3 of 4. " + FUZZED,
        "option httpslog; the CLF form (httplog clf is not supported); a log-format of your own; HAProxy 2.4 and "
        "older. Not picked by -f auto (read as syslog when it has the syslog prefix).",
    ),
    "postgresql": FormatChecks(
        "Real PostgreSQL 13, 14, 15, 16 and 17 in Docker, 15 settings of the prefix, time zone and verbosity, every "
        "record compared with the server's own csvlog; Filebeat's samples of PostgreSQL 9.5 to 13, 12 of 12. " + FUZZED,
        "jsonlog (PostgreSQL 15 and later); the syslog and eventlog destinations; a prefix that does not start with a "
        "time; other lc_messages languages. The zone name (CEST) is not applied. Not picked by -f auto.",
    ),
    "postgresql-csv": FormatChecks(
        "Real PostgreSQL 13, 14, 15, 16 and 17 in Docker, every record compared with the server's stderr log; "
        "Filebeat's samples of PostgreSQL 11 and 13, 10 of 10. " + FUZZED,
        "The syslog and eventlog destinations; other lc_messages languages. The zone name (CEST) is not applied. "
        "Not picked by -f auto.",
    ),
    "log4j": FormatChecks(
        "Real log4j2 2.25.2, logback 1.5.18 and log4j 1.x (reload4j 1.2.25) on Java 17 and 21, 23 patterns and zones, "
        "every record compared with the program's own record; two patterns of Kafka from Filebeat, 8 of 8. " + FUZZED,
        "JsonTemplateLayout, %replace, %highlight, %d{UNIX}; rolling files; Android and Kotlin loggers. "
        "Not picked by -f auto (the pattern is a setting of the program).",
    ),
    "docker-json": FormatChecks(
        "Real Docker 28.3, json-file with and without a terminal, every line compared with what the container "
        "printed, including a line of 50,000 characters that Docker splits; Filebeat and Fluent Bit tests, 8 of 8. "
        "Picked by -f auto. " + FUZZED,
        "Drivers other than json-file (local, journald, syslog); rotated files; entries with attrs or tag.",
    ),
    "github-actions": FormatChecks(
        "The job logs of this project's own workflow runs, 39 of 39. " + FUZZED,
        "Runs of other projects; GitHub Enterprise Server; self-hosted runners. Not picked by -f auto.",
    ),
}


def format_checks(name: str) -> FormatChecks | None:
    """Return what the built-in format ``name`` was checked on, or ``None`` for any other name."""
    return CHECKS.get(name)


def markdown_table() -> str:
    """Return the table of ``docs/guide.md``: one row for each format, in name order.

    ``python -m logfold.plugins.validation`` prints it, to paste between the markers of the guide.
    """
    rows = ["| Format | Checked on | Not checked |", "|---|---|---|"]
    rows += [f"| `{name}` | {item.checked} | {item.not_checked} |" for name, item in sorted(CHECKS.items())]
    return chr(10).join(rows)


if __name__ == "__main__":
    sys.stdout.write(markdown_table() + chr(10))
