"""Check the built-in log formats against the real programs that write such logs.

The tests of the formats read logs that we generated from our own idea of the format, so they cannot show a wrong idea.
Here a real program writes the log and the expected result comes from the program, not from us:

* ``postgresql`` PostgreSQL 13 to 17 writes the same events to the ``stderr`` log and to ``csvlog`` at once. The rows of
                 the csvlog (read with Python's ``csv`` module) say how many entries there are, how many lines each one
                 makes in the ``stderr`` log (the message and its DETAIL, HINT, QUERY, CONTEXT, STATEMENT and LOCATION
                 lines) and the severity of each. ``-f postgresql``, ``-f postgresql-csv`` and ``-f auto`` must agree
                 with that: records, lines that were not parsed, records per level and the time range.

Usage: ``python bench/validate/formats.py [postgresql|haproxy|docker-json|log4j] [--versions 13 14 15 16 17]``
``[--rounds N] [--only NAME]``. The HAProxy, docker-json and Java (log4j2, logback, log4j 1.x) checks are in
``formats_haproxy.py``, ``formats_dockerjson.py`` and ``formats_java.py``; the results are in
``bench/docs/FORMAT_VALIDATION.md``.

Containers are named ``logfold-validate-*`` and removed at the end. Needs ``docker`` and the extension built
(``maturin develop --release``).
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import logfold

POSTGRES_IMAGES = {
    13: "postgres:13.23",
    14: "postgres:14.24",
    15: "postgres:15.19",
    16: "postgres:16.15",
    17: "postgres:17.11",
}
PREFIXES = {
    "default": "%m [%p] ",
    "user-db": "%m [%p] %q%u@%d ",
    "plain-t": "%t ",
    "rds": "%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h ",
}
LEVEL_OF = {"INFO": "INFO", "NOTICE": "INFO", "WARNING": "WARN", "ERROR": "ERROR", "FATAL": "FATAL", "PANIC": "FATAL"}
"""The level that a PostgreSQL severity stands for. LOG, DEBUGn and the extra lines have none (documented)."""
CSV_COLUMNS = {"time": 0, "severity": 11, "message": 13, "detail": 14, "hint": 15, "query_internal": 16, "context": 18}
CSV_COLUMNS |= {"statement": 19, "location": 21, "sqlstate": 12, "position": 20, "internal_position": 17}
EXTRA_LINES = (("detail", "DETAIL"), ("hint", "HINT"), ("query_internal", "QUERY"), ("context", "CONTEXT"))
EXTRA_LINES += (("location", "LOCATION"), ("statement", "STATEMENT"))
LOG_DIRECTORY = "/tmp/pglog"


@dataclass
class Case:
    """One server setting to check."""

    version: int
    prefix: str
    timezone: str = "UTC"
    verbose: bool = False
    name: str = ""

    def label(self) -> str:
        """Return a short name for the table."""
        extra = ("+verbose" if self.verbose else "") + ("" if self.timezone == "UTC" else f" {self.timezone}")
        return f"{self.version} {self.prefix}{extra}"


@dataclass
class Outcome:
    """What one case found."""

    case: Case
    entries: int = 0
    lines: int = 0
    problems: list[str] = field(default_factory=list)
    auto: str = ""


def docker(
    *args: str, check: bool = True, stdin: str | None = None, timeout: float = 300
) -> subprocess.CompletedProcess[str]:
    """Run ``docker`` and return the finished process with its text output.

    The input goes as bytes: in text mode Windows would turn every line feed of a script into CR LF and so change the
    statements that the server logs.
    """
    done = subprocess.run(
        ["docker", *args],
        input=None if stdin is None else stdin.encode("utf-8"),
        capture_output=True,
        check=check,
        timeout=timeout,
    )
    return subprocess.CompletedProcess(
        done.args, done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")
    )


@contextmanager
def server(case: Case, index: int) -> Iterator[str]:
    """Start a PostgreSQL container with both log destinations on, and remove it at the end."""
    name = f"logfold-validate-pg{case.version}-{index}"
    docker("rm", "-f", name, check=False)
    settings = {
        "logging_collector": "on",
        "log_destination": "stderr,csvlog",
        "log_directory": LOG_DIRECTORY,
        "log_filename": "pg.log",
        "log_line_prefix": PREFIXES[case.prefix],
        "log_timezone": case.timezone,
        "log_min_messages": "info",
        "log_min_duration_statement": "0",
        "log_error_verbosity": "verbose" if case.verbose else "default",
        "deadlock_timeout": "200ms",
    }
    arguments = [f"{key}={value}" for key, value in settings.items()]
    flags = [item for argument in arguments for item in ("-c", argument)]
    docker(
        "run",
        "-d",
        "--name",
        name,
        "-e",
        "POSTGRES_PASSWORD=logfold",
        POSTGRES_IMAGES[case.version],
        "postgres",
        *flags,
    )
    try:
        wait_ready(name)
        yield name
    finally:
        docker("rm", "-f", name, check=False)


def wait_ready(name: str, seconds: float = 90) -> None:
    """Wait until the final server (not the temporary one of the first start) answers on TCP."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = docker("exec", name, "psql", "-h", "127.0.0.1", "-U", "postgres", "-tAc", "select 1", check=False)
        if result.stdout.strip() == "1":
            return
        time.sleep(1)
    raise RuntimeError(f"{name} did not become ready: {docker('logs', name, check=False).stderr[-500:]}")


def psql(name: str, script: str, user: str = "postgres", database: str = "postgres") -> None:
    """Run a script in psql; an error in one statement does not stop the next ones."""
    docker(
        "exec",
        "-i",
        name,
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        user,
        "-d",
        database,
        "-q",
        "-f",
        "-",
        check=False,
        stdin=script,
    )


def emit(name: str, events: int) -> int:
    """Write numbered events of every kind to the server log; return how many statements were sent."""
    psql(name, "CREATE ROLE appuser LOGIN; CREATE DATABASE app OWNER appuser;")
    lines = ["SET application_name = 'logfold-validate';"]
    for number in range(1, events + 1):
        lines += [
            f"DO $$ BEGIN RAISE LOG 'evt {number} log'; END $$;",
            f"DO $$ BEGIN RAISE INFO 'evt {number} info'; END $$;",
            f"DO $$ BEGIN RAISE NOTICE 'evt {number} notice'; END $$;",
            f"DO $$ BEGIN RAISE WARNING 'evt {number} warning'; END $$;",
            f"DO $$ BEGIN RAISE EXCEPTION 'evt {number} error' USING DETAIL = E'first detail line\\nsecond line', HINT = 'try again'; END $$;",
            f"SELEC {number};",
            f"SELECT {number},\n       'multi\nline text' AS \"two\nlines\"\n  FROM generate_series(1, 2);",
        ]
    psql(name, "\n".join(lines) + "\n", "appuser", "app")
    docker(
        "exec",
        name,
        "psql",
        "-h",
        "127.0.0.1",
        "-U",
        "appuser",
        "-d",
        "no_such_database",
        "-c",
        "select 1",
        check=False,
    )
    deadlock(name)
    return len(lines)


def deadlock(name: str) -> None:
    """Make two sessions wait for each other, so that the server writes its multi-line deadlock report."""
    psql(name, "CREATE TABLE dl (a int PRIMARY KEY); INSERT INTO dl VALUES (1), (2);", "appuser", "app")
    first = "BEGIN; UPDATE dl SET a = a WHERE a = 1; SELECT pg_sleep(1); UPDATE dl SET a = a WHERE a = 2; COMMIT;"
    second = "BEGIN; UPDATE dl SET a = a WHERE a = 2; SELECT pg_sleep(1); UPDATE dl SET a = a WHERE a = 1; COMMIT;"
    sessions = [threading.Thread(target=psql, args=(name, script, "appuser", "app")) for script in (first, second)]
    for session in sessions:
        session.start()
    for session in sessions:
        session.join()


def collect(name: str, folder: Path) -> tuple[Path, Path]:
    """Stop the server, so that both files are complete, and copy them out."""
    docker("stop", "-t", "30", name)
    stderr_log, csv_log = folder / "pg.log", folder / "pg.csv"
    docker("cp", f"{name}:{LOG_DIRECTORY}/pg.log", str(stderr_log))
    docker("cp", f"{name}:{LOG_DIRECTORY}/pg.csv", str(csv_log))
    return stderr_log, csv_log


def read_csv(path: Path) -> tuple[list[list[str]], list[int]]:
    """Read the rows of a csvlog file and the number of physical lines each row takes."""
    rows: list[list[str]] = []
    spans: list[int] = []
    with open(path, encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        before = 0
        for row in reader:
            rows.append(row)
            spans.append(reader.line_num - before)
            before = reader.line_num
    return rows, spans


def wall_clock(text: str) -> datetime:
    """Read the time of a csvlog row without its zone name (``2026-10-15 10:00:00.123 UTC``)."""
    return datetime.fromisoformat(" ".join(text.split()[:2]))


@dataclass
class Expected:
    """What the csvlog says that the stderr log and the csv file hold."""

    entries: int
    lines: int
    csv_levels: Counter[str]
    line_levels: Counter[str]
    first: datetime
    last: datetime


def expectation(rows: list[list[str]]) -> Expected:
    """Count entries, stderr lines and levels from the rows of a csvlog."""
    csv_levels: Counter[str] = Counter()
    line_levels: Counter[str] = Counter()
    lines = 0
    for row in rows:
        level = LEVEL_OF.get(row[CSV_COLUMNS["severity"]])
        extras = sum(1 for key, _ in EXTRA_LINES if row[CSV_COLUMNS[key]])
        lines += 1 + extras
        if level:
            csv_levels[level] += 1
            line_levels[level] += 1
    times = [wall_clock(row[CSV_COLUMNS["time"]]) for row in rows]
    return Expected(len(rows), lines, csv_levels, line_levels, min(times), max(times))


Record = tuple[str | None, str, int]
"""A record as ``(level, first line of the message, physical lines)``."""


def first_line(text: str) -> str:
    """Return the first line of a message."""
    return text.split("\n", 1)[0]


def expected_stderr_records(rows: list[list[str]], verbose: bool) -> list[Record]:
    """List the records that the stderr log must hold: the message and then each extra line of an entry.

    The server adds `` at character N`` to a one-line message that has a position, and the SQLSTATE and a colon in front
    of it when ``log_error_verbosity`` is ``verbose``.
    """
    records: list[Record] = []
    for row in rows:
        message = row[CSV_COLUMNS["message"]]
        position = row[CSV_COLUMNS["position"]] or row[CSV_COLUMNS["internal_position"]]
        if position and "\n" not in message:
            message += f" at character {position}"
        if verbose:
            message = f"{row[CSV_COLUMNS['sqlstate']]}: {message}"
        records.append((LEVEL_OF.get(row[CSV_COLUMNS["severity"]]), first_line(message), message.count("\n") + 1))
        for key, _ in EXTRA_LINES:
            text = row[CSV_COLUMNS[key]]
            if text:
                records.append((None, first_line(text), text.count("\n") + 1))
    return records


def expected_csv_records(rows: list[list[str]], spans: list[int]) -> list[Record]:
    """List the records of the csv file: one per row, as many physical lines as the row takes."""
    return [
        (
            LEVEL_OF.get(row[CSV_COLUMNS["severity"]]),
            first_line(row[CSV_COLUMNS["message"]]).replace('"', '""'),
            span,
        )
        for row, span in zip(rows, spans, strict=True)
    ]


def compare_records(label: str, path: Path, format: str, want: list[Record], problems: list[str]) -> None:
    """Add a problem for the records of the file that differ from the expected ones.

    The records are compared as a multiset: two sessions that log at the same moment (the deadlock) reach the stderr
    log and the csv file in different orders, so the order of such entries is not something the server promises.
    """
    seen = logfold.inspect_file(path, format=format, sample_lines=10_000_000, limit=10_000_000)
    got = Counter((record.level, first_line(record.message), record.lines) for record in seen.shown)
    expected = Counter(want)
    if len(seen.shown) != len(want):
        problems.append(f"{label}: {len(seen.shown)} records shown, expected {len(want)}")
    extra, missing = list((got - expected).elements()), list((expected - got).elements())
    for record in extra[:2]:
        problems.append(f"{label}: read {record!r}, the server wrote nothing like it")
    for record in missing[:2]:
        problems.append(f"{label}: the server wrote {record!r}, not read like that")
    if len(extra) > 2 or len(missing) > 2:
        problems.append(f"{label}: {max(len(extra), len(missing))} records differ in all")


def compare(label: str, found: logfold.AnalysisResult, records: int, levels: Counter[str], problems: list[str]) -> None:
    """Add a problem for every number of ``found`` that differs from the expected one."""
    run = found.run
    if run.records != records:
        problems.append(f"{label}: {run.records} records, the server wrote {records}")
    if run.unparsed:
        problems.append(f"{label}: {run.unparsed} lines were not parsed")
    if dict(found.levels) != dict(levels):
        problems.append(f"{label}: levels {dict(found.levels)}, the server wrote {dict(levels)}")


def wall(moment: datetime | None) -> datetime | None:
    """Return a time without its zone, as the log wrote it."""
    return moment.replace(tzinfo=None) if moment else None


def time_range(path: Path, format: str) -> tuple[datetime | None, datetime | None]:
    """Return the first and the last time that logfold reads from the file, as wall-clock times."""
    seen = logfold.inspect_file(path, format=format, sample_lines=10_000_000, limit=0)
    return wall(seen.first_time), wall(seen.last_time)


def run_case(case: Case, index: int, events: int) -> Outcome:
    """Run one server setting and compare what logfold reads with what the server wrote."""
    outcome = Outcome(case)
    with server(case, index) as name, tempfile.TemporaryDirectory() as folder:
        emit(name, events)
        stderr_log, csv_log = collect(name, Path(folder))
        rows, spans = read_csv(csv_log)
        want = expectation(rows)
        outcome.entries, outcome.lines = want.entries, want.lines
        problems = outcome.problems
        compare("postgresql", logfold.analyze(stderr_log, format="postgresql"), want.lines, want.line_levels, problems)
        compare(
            "postgresql-csv", logfold.analyze(csv_log, format="postgresql-csv"), want.entries, want.csv_levels, problems
        )
        compare_records("postgresql", stderr_log, "postgresql", expected_stderr_records(rows, case.verbose), problems)
        compare_records("postgresql-csv", csv_log, "postgresql-csv", expected_csv_records(rows, spans), problems)
        for label, path, format in (
            ("postgresql", stderr_log, "postgresql"),
            ("postgresql-csv", csv_log, "postgresql-csv"),
        ):
            first, last = time_range(path, format)
            expected = (want.first, want.last)
            if label == "postgresql" and "%m" not in PREFIXES[case.prefix]:
                expected = (want.first.replace(microsecond=0), want.last.replace(microsecond=0))
            if (first, last) != expected:
                problems.append(
                    f"{label}: time range {first} to {last}, the server wrote {expected[0]} to {expected[1]}"
                )
        try:
            outcome.auto = logfold.analyze(stderr_log, format="auto").meta.format
        except logfold.FormatError:
            outcome.auto = "refused"
        if problems:
            shutil.copy(stderr_log, Path(tempfile.gettempdir()) / f"logfold-validate-{name}.log")
            shutil.copy(csv_log, Path(tempfile.gettempdir()) / f"logfold-validate-{name}.csv")
    return outcome


def cases(versions: list[int], only: str | None) -> list[Case]:
    """Return the settings to check: every version with two prefixes, the other settings on the newest."""
    chosen: list[Case] = []
    for version in versions:
        chosen += [Case(version, "default"), Case(version, "user-db")]
    newest = max(versions)
    chosen += [Case(newest, "plain-t"), Case(newest, "rds"), Case(newest, "default", verbose=True)]
    chosen += [Case(newest, "default", timezone="America/New_York"), Case(newest, "rds", timezone="Asia/Kolkata")]
    return [case for case in chosen if only is None or only in case.label()]


def run_postgresql(args: argparse.Namespace) -> int:
    """Run the PostgreSQL cases, print their table and return the number that failed."""
    print("| setting | entries | stderr lines | auto picks | result |")
    print("|---|---:|---:|---|---|")
    failed = 0
    for index, case in enumerate(cases(args.versions, args.only)):
        outcome = run_case(case, index, args.events)
        failed += bool(outcome.problems)
        verdict = "all numbers match" if not outcome.problems else "; ".join(outcome.problems)
        print(f"| {case.label()} | {outcome.entries} | {outcome.lines} | {outcome.auto} | {verdict} |", flush=True)
    return failed


def run_haproxy_cases(args: argparse.Namespace) -> int:
    """Run the HAProxy cases, print their table and return the number that failed."""
    from formats_haproxy import HAPROXY_IMAGES, LOG_FORMATS, HaproxyCase, run_haproxy

    chosen = [HaproxyCase(version, form) for version in HAPROXY_IMAGES for form in LOG_FORMATS]
    chosen.append(HaproxyCase(max(HAPROXY_IMAGES), "raw", "httplog clf"))
    print("| setting | requests | log lines | result |")
    print("|---|---:|---:|---|")
    failed = 0
    for index, case in enumerate(c for c in chosen if args.only is None or args.only in c.label()):
        outcome = run_haproxy(case, index, args.rounds)
        failed += bool(outcome.problems)
        verdict = outcome.note or ("all numbers match" if not outcome.problems else "; ".join(outcome.problems))
        print(f"| {case.label()} | {outcome.requests} | {outcome.lines} | {verdict} |", flush=True)
    return failed


def run_dockerjson_cases(args: argparse.Namespace) -> int:
    """Run the docker-json cases, print their table and return the number that failed."""
    from formats_dockerjson import DockerJsonCase, run_dockerjson

    chosen = [DockerJsonCase("json-file"), DockerJsonCase("json-file with a tty (CR LF)", tty=True)]
    print("| setting | entries | result |")
    print("|---|---:|---|")
    failed = 0
    for index, case in enumerate(c for c in chosen if args.only is None or args.only in c.name):
        outcome = run_dockerjson(case, index, args.rounds)
        failed += bool(outcome.problems)
        verdict = "all numbers match" if not outcome.problems else "; ".join(outcome.problems)
        pieces = f" ({outcome.note})" if outcome.note else ""
        print(f"| {case.name} | {outcome.entries} | {verdict}{pieces} |", flush=True)
    return failed


def run_java_cases(args: argparse.Namespace) -> int:
    """Run the log4j and logback cases against real Java libraries; return the number that failed."""
    from formats_java import run_java_cases as run

    return run(args)


def main() -> None:
    """Run the cases of the chosen programs and print one table for each; exit with 1 when any number differs."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "target", nargs="?", default="postgresql", choices=["postgresql", "haproxy", "docker-json", "log4j"]
    )
    parser.add_argument("--versions", nargs="+", type=int, default=sorted(POSTGRES_IMAGES), help="PostgreSQL majors")
    parser.add_argument("--events", type=int, default=20, help="PostgreSQL: rounds of the emitter")
    parser.add_argument("--rounds", type=int, default=20, help="HAProxy, Java: rounds of events")
    parser.add_argument("--only", help="run the cases whose label contains this text")
    args = parser.parse_args()
    if not logfold._bridge.is_available():
        sys.exit("the native extension is not built: run `maturin develop --release`")
    runners = {
        "postgresql": run_postgresql,
        "haproxy": run_haproxy_cases,
        "docker-json": run_dockerjson_cases,
        "log4j": run_java_cases,
    }
    failed = runners[args.target](args)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
