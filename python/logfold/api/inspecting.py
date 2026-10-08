"""Looking at how a file is read: the format, the first records as parsed and the levels of a sample."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from logfold import _bridge
from logfold.engines.native import format_to_dict
from logfold.errors import read_error
from logfold.ext.formats import FormatSpec
from logfold.formats import resolve_format
from logfold.formats.auto import read_sample
from logfold.timestamps import micros_to_datetimes

SAMPLE_LINES = 1000
SHOWN_RECORDS = 10
_GZIP_MAGIC = b"\x1f\x8b"


@dataclass(frozen=True, slots=True)
class InspectedRecord:
    """One record of the sample as the format parsed it.

    Attributes:
        message: The message, continuation lines included.
        time: Parsed timestamp, or ``None``.
        level: Level name, or ``None``.
        lines: Physical lines the record spans.
    """

    message: str
    time: datetime | None
    level: str | None
    lines: int


@dataclass(frozen=True, slots=True)
class Inspection:
    """What reading the start of a file shows.

    Attributes:
        path: The inspected file.
        size: Size on disk in bytes.
        compressed: Whether the file is gzip-compressed.
        spec: The format that was applied.
        confidence: Detection confidence, ``None`` unless the format was auto-detected.
        multiline_auto: Whether multiline was switched on because the sample looked multiline.
        lines: Non-blank lines in the sample.
        records: Records parsed from the sample.
        unparsed: Sampled lines that did not become part of a record.
        truncated: Whether the file has more lines than the sample.
        shown: The first records.
        levels: Records per level name in the sample (levels that occurred, least severe first).
        no_level: Records without a level.
        first_time: Earliest timestamp in the sample, or ``None``.
        last_time: Latest timestamp in the sample, or ``None``.
    """

    path: str
    size: int
    compressed: bool
    spec: FormatSpec
    confidence: float | None
    multiline_auto: bool
    lines: int
    records: int
    unparsed: int
    truncated: bool
    shown: tuple[InspectedRecord, ...]
    levels: Mapping[str, int]
    no_level: int
    first_time: datetime | None
    last_time: datetime | None


def inspect_file(
    path: str | os.PathLike[str],
    *,
    format: str = "auto",
    multiline: bool | None = None,
    limit: int = SHOWN_RECORDS,
    sample_lines: int = SAMPLE_LINES,
) -> Inspection:
    """Read the start of a file with a format and report what came out.

    Args:
        path: The file; ``.gz`` is decompressed transparently, standard input is not supported.
        format: ``auto``, a registered name or ``regex:<pattern>``.
        multiline: Override of the multiline flag, as in :func:`logfold.analyze`.
        limit: Records to keep in ``shown``.
        sample_lines: Non-blank lines to read.

    Returns:
        The inspection.

    Raises:
        FormatError: If the format is unknown, invalid or cannot be detected.
        SourceError: If the file cannot be read, or the path is standard input.
    """
    name = os.fspath(path)
    resolved = resolve_format(format, [name], multiline)
    lines = read_sample(name, sample_lines + 1)
    truncated = len(lines) > sample_lines
    lines = lines[:sample_lines]
    try:
        size = os.stat(name).st_size
        with open(name, "rb") as handle:
            compressed = handle.read(2) == _GZIP_MAGIC
    except OSError as error:
        raise read_error(name, error) from error

    sample = "\n".join(lines)
    answer = _bridge.inspect_sample(sample.encode("utf-8"), format_to_dict(resolved.spec), max(limit, 0))
    shown = []
    for record in answer["shown"]:
        (moment,) = micros_to_datetimes([record["time"]], record["tz_aware"])
        shown.append(InspectedRecord(record["message"], moment, record["level"], record["lines"]))
    first = last = None
    if answer["first"] is not None:
        first, last = micros_to_datetimes([answer["first"], answer["last"]], answer["tz_aware"])
    return Inspection(
        path=name,
        size=size,
        compressed=compressed,
        spec=resolved.spec,
        confidence=resolved.confidence,
        multiline_auto=resolved.multiline_auto,
        lines=len(lines),
        records=answer["records"],
        unparsed=answer["unparsed"],
        truncated=truncated,
        shown=tuple(shown),
        levels=answer["levels"],
        no_level=answer["no_level"],
        first_time=first,
        last_time=last,
    )
