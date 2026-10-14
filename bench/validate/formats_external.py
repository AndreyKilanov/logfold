"""Check the built-in formats against logs that other projects wrote, with the parse that they expect (V2).

``external_samples.py`` downloads the samples at pinned commits. Every sample becomes a list of expected events, each with
the text of the event, how many lines it takes, a time and a level when they are known, from one of three oracles:

* ``expected``: the ``*-expected.json`` of a Filebeat module test. The text of an event is the bytes of the log from its
  ``log.offset`` to the next one (so the boundaries come from Filebeat, not from us), the time is ``@timestamp``, the level
  ``log.level``. Filebeat keeps at most 100 events in such a file, so a longer log is only compared as far as it goes.
* ``docker``: the lines of a Docker ``json-file`` log read with Python's ``json``; an entry whose ``log`` does not end in a
  line break is joined with the next one, as ``docker logs`` prints it.
* ``lines``: every non-blank line is one event; the time and the level are cut from the line with the regexes of the manifest.

What is compared with what ``logfold`` reads: the number of records and of lines that were not parsed, that every non-blank
line of the file is in a record or in the unparsed count, and record by record, in order, the number of lines, the message
(it must lie inside the text of the event), the time and the level (only a level that ``logfold`` knows).

Usage: ``python bench/validate/formats_external.py [--only TEXT] [--github-actions]``.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from external_gha import samples as gha_samples
from external_samples import EXPECTED, Sample, fetch

import logfold

LEVELS = {"warning": "WARN", "warn": "WARN", "err": "ERROR", "critical": "FATAL", "crit": "FATAL", "panic": "FATAL"}
LOGFOLD_LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"})
MAX_SHOWN = 2
MIN_SAMPLES = 20
EVENT_CAP = 100
"""Filebeat keeps at most this many events in an expected file, so a file with more records was cut."""
NO_YEAR = 1970
"""The year that a time without a year (classic syslog) gets."""
ZONE_ONLY = "zone only"
JSON_FORMATS = frozenset({"jsonl", "docker-json", "serilog-clef", "journald"})
"""Formats whose message is read from a JSON string, so it is not a piece of the raw text (escapes)."""
LF = "\n"


@dataclass
class Event:
    """One expected event."""

    text: str
    lines: int
    time: str | None = None
    level: str | None = None
    raw: bool = True


@dataclass
class Outcome:
    """What one sample found."""

    sample: Sample
    events: int = 0
    records: int = 0
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def non_blank(text: str) -> int:
    """Count the lines of a text that are not blank."""
    return sum(1 for line in text.splitlines() if line.strip())


def first_line(text: str) -> str:
    """Return the first line of a message."""
    return text.split(LF, 1)[0]


def normal_level(text: str) -> str:
    """Return the name that ``logfold`` uses for a level of the expected events."""
    return LEVELS.get(text.lower(), text.upper())


def as_utc(moment: datetime) -> datetime:
    """Return a time in UTC; a time without a zone is taken as UTC."""
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def parse_time(text: str) -> datetime | None:
    """Read an ISO time of an expected event (nanoseconds are cut to microseconds); ``None`` when it does not read."""
    text = re.sub(r"(\.\d{6})\d+", r"\1", text.replace("Z", "+00:00"))
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def filebeat_events(sample: Sample, data: bytes) -> list[Event]:
    """Build the events from the expected file of a Filebeat module test."""
    assert sample.expected is not None
    raw: list[dict[str, Any]] = json.loads(sample.expected.read_text(encoding="utf-8"))
    by_offset = all(isinstance(item.get("log.offset"), int) for item in raw)
    if by_offset:
        raw.sort(key=lambda item: item["log.offset"])
        offsets = [item["log.offset"] for item in raw]
        ends = [*offsets[1:], len(data)]
        texts = [data[start:end].decode("utf-8", "replace") for start, end in zip(offsets, ends, strict=True)]
    else:
        texts = [str(item.get("event.original") or item.get("message") or "") for item in raw]
    return [
        Event(text, non_blank(text), item.get("@timestamp"), item.get("log.level"), by_offset)
        for item, text in zip(raw, texts, strict=True)
    ]


def docker_events(data: bytes) -> tuple[list[Event], int]:
    """Build the events of a Docker ``json-file`` log (the entries of one printed line are one event) and count the lines
    that are not JSON."""
    events: list[Event] = []
    pending: list[dict[str, Any]] = []
    broken = 0
    for line in data.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            broken += 1
            continue
        pending.append(entry)
        if str(entry.get("log", "")).endswith(LF):
            text = "".join(str(item.get("log", "")) for item in pending).removesuffix(LF).removesuffix("\r")
            events.append(Event(text, len(pending), pending[0].get("time")))
            pending = []
    if pending:
        text = "".join(str(item.get("log", "")) for item in pending)
        events.append(Event(text, len(pending), pending[0].get("time")))
    return events, broken


def line_events(sample: Sample, data: bytes) -> list[Event]:
    """Build the events of a log whose lines are the events, with the time and the level cut out by manifest regexes.

    With ``start_re`` only the lines that match it start an event, and the other lines join the event before them.
    """
    time_re, level_re = sample.options.get("time_re"), sample.options.get("level_re")
    start_re = sample.options.get("start_re")
    groups: list[list[str]] = []
    for line in data.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        if start_re and groups and not re.search(start_re, line):
            groups[-1].append(line)
        else:
            groups.append([line])
    events: list[Event] = []
    for group in groups:
        found_time = re.search(time_re, group[0]) if time_re else None
        found_level = re.search(level_re, group[0]) if level_re else None
        stamp = found_time.group(1) if found_time else None
        events.append(Event(LF.join(group), len(group), stamp, found_level.group(1) if found_level else None))
    return events


def time_problem(record_time: datetime | None, stamp: str, no_year: bool) -> str | None:
    """Compare the time of a record with the expected one; a difference of only a zone offset is not a problem here."""
    wanted = parse_time(stamp)
    if wanted is None:
        return None
    if record_time is None:
        return f"no time, expected {stamp}"
    record_time = record_time.replace(microsecond=record_time.microsecond // 1000 * 1000)
    wanted = wanted.replace(microsecond=wanted.microsecond // 1000 * 1000)
    if no_year and record_time.year == NO_YEAR:
        wanted, record_time = wanted.replace(year=2000), record_time.replace(year=2000)
    if record_time.tzinfo is not None:
        return None if as_utc(record_time) == as_utc(wanted) else f"time {record_time}, expected {stamp}"
    if record_time == wanted.replace(tzinfo=None) or as_utc(record_time) == as_utc(wanted):
        return None
    shift = (as_utc(record_time) - as_utc(wanted)).total_seconds()
    if shift % 900 == 0 and abs(shift) <= 14 * 3600:
        return ZONE_ONLY
    return f"time {record_time}, expected {stamp}"


def expected_events(sample: Sample, data: bytes) -> tuple[list[Event], int]:
    """Return the events that the oracle of the sample expects and how many lines it expects to stay unparsed."""
    if sample.oracle == EXPECTED:
        return filebeat_events(sample, data), 0
    if sample.oracle == "docker":
        return docker_events(data)
    return line_events(sample, data), 0


def check(sample: Sample) -> Outcome:
    """Read one sample with the format that is meant for it and compare it with the expected events."""
    outcome = Outcome(sample)
    data = sample.log.read_bytes()
    events, broken = expected_events(sample, data)
    outcome.events = len(events)
    try:
        seen = logfold.inspect_file(sample.log, format=sample.format, sample_lines=10_000_000, limit=10_000_000)
    except logfold.FormatError as error:
        outcome.problems.append(f"the format was refused: {str(error).splitlines()[0][:120]}")
        return outcome
    outcome.records = seen.records
    problems = outcome.problems
    capped = sample.oracle == EXPECTED and len(events) >= EVENT_CAP
    if seen.records != len(events) and not (capped and seen.records > len(events)):
        problems.append(f"{seen.records} records, {len(events)} events expected")
    in_file = non_blank(data.decode("utf-8", "replace"))
    shown_lines = sum(record.lines for record in seen.shown) + seen.unparsed
    accounted = seen.lines if sample.oracle == "docker" else shown_lines
    if accounted != in_file:
        problems.append(f"{accounted} lines in records and unparsed, the file has {in_file}")
    if seen.unparsed != broken:
        problems.append(f"{seen.unparsed} lines were not parsed, {broken} expected")
    wrong: dict[str, list[str]] = {"lines": [], "message": [], "time": [], "level": []}
    zone_only = 0
    no_year = bool(sample.options.get("no_year"))
    for index, (event, record) in enumerate(zip(events, seen.shown, strict=False), 1):
        who = f"event {index}"
        last_of_cut = capped and index == len(events)
        if event.lines and record.lines != event.lines and not last_of_cut and sample.oracle != "docker":
            wrong["lines"].append(f"{who}: {record.lines} lines, expected {event.lines}")
        if (
            event.raw
            and event.text
            and sample.format not in JSON_FORMATS
            and first_line(record.message) not in event.text
        ):
            wrong["message"].append(f"{who}: message {first_line(record.message)[:50]!r} is not in the event")
        if event.time:
            found = time_problem(record.time, event.time, no_year)
            if found == ZONE_ONLY:
                zone_only += 1
            elif found:
                wrong["time"].append(f"{who}: {found}")
        if event.level and normal_level(event.level) in LOGFOLD_LEVELS and record.level != normal_level(event.level):
            wrong["level"].append(f"{who}: level {record.level}, expected {event.level}")
    for kind, found_list in wrong.items():
        problems.extend(found_list[:MAX_SHOWN])
        if len(found_list) > MAX_SHOWN:
            problems.append(f"{len(found_list)} events differ in {kind}")
    if zone_only:
        outcome.notes.append(f"{zone_only} times differ only by the zone (the zone name is not applied)")
    return outcome


def main() -> None:
    """Check every sample, print a table and exit with 1 when any differs."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="check the samples whose format or name contains this text")
    parser.add_argument(
        "--github-actions", action="store_true", help="also check real logs of workflow runs (needs gh)"
    )
    args = parser.parse_args()
    if not logfold._bridge.is_available():
        sys.exit("the native extension is not built: run `maturin develop --release`")
    every = fetch()
    if args.github_actions:
        every += gha_samples()
    samples = [s for s in every if args.only is None or args.only in s.format or args.only in s.name]
    print("| format | sample | events | records | result |")
    print("|---|---|---:|---:|---|")
    failed = 0
    per_format: dict[str, list[bool]] = {}
    for sample in samples:
        outcome = check(sample)
        failed += bool(outcome.problems)
        per_format.setdefault(sample.format, []).append(not outcome.problems)
        verdict = "match" if not outcome.problems else "; ".join(outcome.problems)
        verdict += "".join(f" [{note}]" for note in outcome.notes)
        print(f"| {sample.format} | {sample.name} | {outcome.events} | {outcome.records} | {verdict} |", flush=True)
    print()
    for name, results in per_format.items():
        few = " (fewer than 20 samples)" if len(results) < MIN_SAMPLES else ""
        print(f"{name}: {sum(results)} of {len(results)} samples match{few}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
