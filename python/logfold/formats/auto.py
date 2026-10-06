"""Format auto-detection by scoring candidates on a sample of lines."""

from __future__ import annotations

import gzip
import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from logfold.errors import FormatDetectionError, FormatError, read_error
from logfold.ext.formats import FormatSpec, JsonFormat, RegexFormat
from logfold.formats.builtin import BUILTIN_FORMATS, DETECTION_ORDER

SAMPLE_LINES = 200
MAX_SAMPLE_LINE_BYTES = 1 << 20
MAX_SAMPLE_BYTES = 8 << 20
CONFIDENCE_THRESHOLD = 0.8
INDENT_CONTINUATION_SCORE = 0.9


class _LineReader(Protocol):
    def readline(self, size: int = -1, /) -> bytes: ...


def _sample_lines(stream: _LineReader) -> Iterator[bytes]:
    """Yield lines of a stream with bounded memory: a longer line is cut and the whole sample has a byte budget."""
    total = 0
    while total < MAX_SAMPLE_BYTES:
        raw = stream.readline(MAX_SAMPLE_LINE_BYTES + 1)
        if not raw:
            return
        total += len(raw)
        if len(raw) > MAX_SAMPLE_LINE_BYTES and not raw.endswith(b"\n"):
            raw = raw[:MAX_SAMPLE_LINE_BYTES]
            while total < MAX_SAMPLE_BYTES:
                rest = stream.readline(MAX_SAMPLE_LINE_BYTES)
                total += len(rest)
                if not rest or rest.endswith(b"\n"):
                    break
        yield raw


def read_sample(path: str, limit: int = SAMPLE_LINES) -> list[str]:
    """Read up to ``limit`` non-blank lines from the start of ``path``.

    Memory is bounded whatever the file holds: a line longer than 1 MiB is cut there and reading stops after 8 MiB.

    Args:
        path: File path; ``.gz`` files are decompressed transparently.
        limit: Maximum number of lines.

    Returns:
        Decoded lines without terminators.

    Raises:
        FormatError: If the path is standard input or a zstd file.
        SourceError: If the file cannot be read.
    """
    if path == "-":
        raise FormatError("auto detection cannot sample standard input; pass an explicit format")
    try:
        with Path(path).open("rb") as probe:
            magic = probe.read(4)
        if magic == b"\x28\xb5\x2f\xfd":
            raise FormatError(f"cannot sample the zstd file {path!r}; pass an explicit format")
        opener = gzip.open if magic[:2] == b"\x1f\x8b" else open
        lines: list[str] = []
        with opener(path, "rb") as stream:
            for raw in _sample_lines(stream):
                line = raw.rstrip(b"\r\n").decode("utf-8", "replace")
                if line.strip():
                    lines.append(line)
                if len(lines) >= limit:
                    break
        return lines
    except OSError as error:
        raise read_error(path, error) from error


@dataclass(frozen=True, slots=True)
class Detection:
    """Outcome of format detection.

    Attributes:
        spec: The chosen specification.
        confidence: Share of sampled lines the format accounts for, in ``[0, 1]``.
        multiline_hint: True when the unmatched lines are all indented, which looks like continuation lines.
    """

    spec: FormatSpec
    confidence: float
    multiline_hint: bool = False


def _matches(spec: FormatSpec, line: str) -> bool:
    if isinstance(spec, JsonFormat):
        try:
            value = json.loads(line)
        except ValueError:
            return False
        return isinstance(value, dict) and any(key in value for key in spec.message_keys)
    if isinstance(spec, RegexFormat):
        return re.search(spec.pattern, line) is not None
    return False


def _score(spec: FormatSpec, lines: Sequence[str]) -> tuple[float, bool]:
    if not lines:
        return 0.0, False
    hits = [_matches(spec, line) for line in lines]
    total = sum(hits) / len(lines)
    body = [hit for line, hit in zip(lines, hits, strict=True) if not line[:1].isspace()]
    if body and len(body) < len(lines):
        body_score = sum(body) / len(body)
        if body_score >= INDENT_CONTINUATION_SCORE:
            return body_score, True
    return total, False


def detect_format(paths: Sequence[str]) -> Detection:
    """Pick the best built-in format for the first input.

    Args:
        paths: Input paths of the run; only the first is sampled.

    Returns:
        The chosen specification, its confidence and whether the sample looks multiline.

    Raises:
        FormatDetectionError: If no candidate reaches the confidence threshold.
    """
    lines = read_sample(paths[0])
    if not lines:
        return Detection(BUILTIN_FORMATS["plain"], 1.0)
    scored = {name: _score(BUILTIN_FORMATS[name], lines) for name in DETECTION_ORDER}
    best_name = max(DETECTION_ORDER, key=lambda name: scored[name][0])
    best_score, hint = scored[best_name]
    if best_score < CONFIDENCE_THRESHOLD:
        ranked = sorted(scored.items(), key=lambda item: -item[1][0])[:3]
        raise FormatDetectionError(paths[0], tuple((name, score) for name, (score, _hint) in ranked))
    return Detection(BUILTIN_FORMATS[best_name], best_score, hint)
