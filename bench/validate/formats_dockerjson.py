"""The ``docker-json`` format against a real Docker ``json-file`` log (used by ``formats.py``).

A container prints numbered lines on stdout and stderr, empty lines, non-ASCII text, escape sequences, quotes and
backslashes, lines longer than 16 KB (which Docker splits into several entries) and a last line without a line break.
The real ``*-json.log`` file is read back and parsed with Python's ``json`` module: every line of the file is one entry,
so the expected records, messages and times come from the file, and the lines that the container printed are rebuilt from
the entries to prove that the file holds what was written.
"""

from __future__ import annotations

import json
import re
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from formats import docker

import logfold

CONTAINER_IMAGE = "python:3.13.7-alpine"
READER_IMAGE = "alpine:3.22.1"
PRINTER = """
import sys
rounds = int(sys.argv[1])
for number in range(1, rounds + 1):
    sys.stdout.write(f"line {number} stdout\\n")
    sys.stderr.write(f"line {number} stderr\\n")
    sys.stdout.write("\\n")
    sys.stdout.write(f"unicode {number}: h\\u00e9llo \\u65e5\\u672c\\u8a9e \\U0001F600\\n")
    sys.stdout.write(f'tab\\there "quoted" back\\\\slash \\x1b[31mred\\x1b[0m {number}\\n')
    if number % 5 == 0:
        sys.stdout.write(f"long {number} " + "y" * 50000 + "\\n")
sys.stdout.write("no line break at exit")
sys.stdout.flush()
"""
NANOSECONDS = re.compile(r"(\.\d{6})\d*Z$")


@dataclass
class DockerJsonCase:
    """One way of running the container."""

    name: str
    tty: bool = False


@dataclass
class DockerJsonOutcome:
    """What one case found."""

    case: DockerJsonCase
    entries: int = 0
    problems: list[str] = field(default_factory=list)


def printed_lines(rounds: int, tty: bool) -> Counter[tuple[str, str]]:
    """Return the lines that the container prints as ``(stream, text)``; a terminal has one stream."""
    printed: Counter[tuple[str, str]] = Counter()
    for number in range(1, rounds + 1):
        printed[("stdout", f"line {number} stdout")] += 1
        printed[("stdout" if tty else "stderr", f"line {number} stderr")] += 1
        printed[("stdout", "")] += 1
        printed[("stdout", f"unicode {number}: héllo 日本語 \U0001f600")] += 1
        printed[("stdout", f'tab\there "quoted" back\\slash \x1b[31mred\x1b[0m {number}')] += 1
        if number % 5 == 0:
            printed[("stdout", f"long {number} " + "y" * 50000)] += 1
    printed[("stdout", "no line break at exit")] += 1
    return printed


def entry_time(text: str) -> datetime:
    """Read the time of an entry (nanoseconds, ``Z``) as a wall-clock time with microseconds."""
    return datetime.fromisoformat(NANOSECONDS.sub(r"\1+00:00", text)).replace(tzinfo=None)


def joined_lines(entries: list[dict[str, str]], terminator: str) -> Counter[tuple[str, str]]:
    """Rebuild the printed lines: an entry that does not end the line is joined with the next one of its stream."""
    lines: Counter[tuple[str, str]] = Counter()
    pending: dict[str, str] = {}
    for entry in entries:
        stream, text = entry["stream"], entry["log"]
        if text.endswith("\n"):
            lines[(stream, (pending.pop(stream, "") + text).removesuffix("\n").removesuffix(terminator))] += 1
        else:
            pending[stream] = pending.get(stream, "") + text
    for stream, text in pending.items():
        lines[(stream, text)] += 1
    return lines


def run_dockerjson(case: DockerJsonCase, index: int, rounds: int) -> DockerJsonOutcome:
    """Run the container, read its ``json-file`` log and compare it with what logfold reads."""
    outcome = DockerJsonOutcome(case)
    name = f"logfold-validate-dockerjson-{index}"
    docker("rm", "-f", name, check=False)
    options = ["-t"] if case.tty else []
    docker(
        "run",
        "-d",
        "--name",
        name,
        "--log-driver",
        "json-file",
        *options,
        CONTAINER_IMAGE,
        "python",
        "-c",
        PRINTER,
        str(rounds),
    )
    try:
        docker("wait", name)
        path = docker("inspect", "-f", "{{.LogPath}}", name).stdout.strip()
        folder, _, file = path.rpartition("/")
        text = docker("run", "--rm", "-v", f"{folder}:/logs:ro", READER_IMAGE, "cat", f"/logs/{file}").stdout
    finally:
        docker("rm", "-f", name, check=False)
    with tempfile.TemporaryDirectory() as scratch:
        log = Path(scratch) / f"{name}-json.log"
        log.write_text(text, encoding="utf-8", newline="")
        check_log(case, log, rounds, outcome)
    return outcome


def check_log(case: DockerJsonCase, log: Path, rounds: int, outcome: DockerJsonOutcome) -> None:
    """Compare the file with the lines that were printed and with what logfold reads from it."""
    problems = outcome.problems
    entries = [json.loads(line) for line in log.read_text(encoding="utf-8").split("\n") if line]
    outcome.entries = len(entries)
    terminator = "\r" if case.tty else ""
    if joined_lines(entries, terminator) != printed_lines(rounds, case.tty):
        problems.append("the lines rebuilt from the file are not the lines that were printed (the oracle is wrong)")
        return
    seen = logfold.inspect_file(log, format="docker-json", sample_lines=10_000_000, limit=10_000_000)
    if seen.records != len(entries):
        problems.append(f"{seen.records} records, the file has {len(entries)} entries")
    if seen.unparsed:
        problems.append(f"{seen.unparsed} lines were not parsed")
    expected = Counter(entry["log"].removesuffix("\n").removesuffix(terminator) for entry in entries)
    got = Counter(record.message for record in seen.shown)
    for message in list((got - expected).elements())[:2]:
        problems.append(f"read {message[:60]!r} ({len(message)} characters), the file has nothing like it")
    for message in list((expected - got).elements())[:2]:
        problems.append(f"the file has {message[:60]!r} ({len(message)} characters), not read like that")
    first = min(entry_time(entry["time"]) for entry in entries)
    last = max(entry_time(entry["time"]) for entry in entries)
    seen_first, seen_last = (
        moment.replace(tzinfo=None) if moment else None for moment in (seen.first_time, seen.last_time)
    )
    if (seen_first, seen_last) != (first, last):
        problems.append(f"time range {seen_first} to {seen_last}, the file has {first} to {last}")
    parts = sum(1 for entry in entries if not entry["log"].endswith("\n"))
    if parts:
        outcome.problems.append(
            f"note: {parts} entries are pieces of a longer line and are read as records of their own"
        )
