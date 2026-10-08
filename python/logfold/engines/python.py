"""Pure-Python reference engine.

A deliberately simple, slow implementation of ``docs/ALGORITHM.md``. It is the oracle that the native engine is tested
against and the fallback when the native extension is unavailable. It always runs the sequential strategy.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any, cast

from logfold.engines import _timeparse as tp
from logfold.engines._reference_tree import Miner, Recount
from logfold.engines.base import MineRequest, MiningResult, ProgressCallback, RunInfo, TemplateTable
from logfold.errors import ConfigError, EngineError, FormatError, SourceError, read_error
from logfold.ext.formats import FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.masks import Masker
from logfold.model import RunMetrics

_ASCII_WS = b" \t\n\x0c\r"
_TICK_BYTES = 1 << 20
MAX_LINE_BYTES = 16 << 20
"""Longest line content in bytes; a longer line keeps its first bytes and the rest is dropped (``ALGORITHM.md`` 1.1)."""
MAX_RECORD_BYTES = 1 << 20
"""A multi-line record takes continuation lines only while it is smaller than this (``ALGORITHM.md`` 1.1)."""

ParsedRecord = tuple[str, "int | None", bool, "int | None"]


class RecordParser:
    """Parses records of a :class:`~logfold.ext.formats.FormatSpec` (``docs/ALGORITHM.md`` §1.2).

    Attributes:
        multiline: Whether lines that do not start a record continue the previous one.
    """

    def __init__(self, spec: FormatSpec) -> None:
        """Compile the patterns of ``spec``.

        Args:
            spec: The format specification.

        Raises:
            FormatError: If the timestamp format is invalid.
        """
        self.multiline = spec.multiline
        self._spec = spec
        self._ts: tp.TsFormat | None = None
        ts_format = getattr(spec, "ts_format", None)
        if ts_format is not None:
            try:
                self._ts = tp.TsFormat(ts_format)
            except ValueError as error:
                raise FormatError(str(error)) from error
        self._regex: re.Pattern[str] | None = None
        self._record_start: re.Pattern[str] | None = None
        if isinstance(spec, RegexFormat):
            self._regex = re.compile(spec.pattern)
        elif isinstance(spec, PlainFormat) and spec.record_start is not None:
            self._record_start = re.compile(spec.record_start)

    def starts_record(self, line: str) -> bool:
        """Tell whether ``line`` is the first line of a record (used for multiline formats)."""
        if isinstance(self._spec, RegexFormat):
            assert self._regex is not None
            return self._regex.search(line) is not None
        if isinstance(self._spec, PlainFormat):
            return self._record_start is not None and self._record_start.search(line) is not None
        return line.lstrip(" \t\n\x0c\r").startswith("{")

    def _time(self, text: str) -> tp.Parsed | None:
        return self._ts.parse(text) if self._ts is not None else tp.parse_iso(text)

    def parse(self, first: str, continuation: str) -> ParsedRecord | None:
        """Parse one record; ``None`` when the first line does not match the format."""
        spec = self._spec
        if isinstance(spec, PlainFormat):
            return first + continuation, None, False, None
        if isinstance(spec, JsonFormat):
            return self._parse_json(first, spec)
        assert isinstance(spec, RegexFormat)
        assert self._regex is not None
        match = self._regex.search(first)
        if match is None:
            return None
        head = first if spec.message_group is None else (match.group(spec.message_group) or "")
        parsed = None
        if spec.time_group is not None and match.group(spec.time_group) is not None:
            parsed = self._time(match.group(spec.time_group))
        level = None
        if spec.level_group is not None and match.group(spec.level_group) is not None:
            level = tp.parse_level(match.group(spec.level_group))
        return head + continuation, parsed[0] if parsed else None, bool(parsed and parsed[1]), level

    def _parse_json(self, text: str, spec: JsonFormat) -> ParsedRecord | None:
        try:
            value = json.loads(text, parse_constant=_reject_constant)
        except ValueError:
            return None
        if not isinstance(value, dict):
            return None
        message = _first_key(value, spec.message_keys)
        if message is _MISSING:
            return None
        rendered = (
            message if isinstance(message, str) else json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        )
        raw_time = _first_key(value, spec.time_keys)
        parsed = None if raw_time is _MISSING else self._json_time(raw_time)
        raw_level = _first_key(value, spec.level_keys)
        level = tp.parse_level(raw_level) if isinstance(raw_level, str) else None
        return rendered, parsed[0] if parsed else None, bool(parsed and parsed[1]), level

    def _json_time(self, value: Any) -> tp.Parsed | None:
        if isinstance(value, str):
            if value and len(value) <= 18 and value.isascii() and value.isdigit():
                micros = tp.epoch_int_to_micros(int(value))
                return None if micros is None else (micros, True)
            return self._time(value)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        if isinstance(value, int) and -(1 << 63) <= value < (1 << 63):
            micros = tp.epoch_int_to_micros(value)
        else:
            micros = tp.epoch_float_to_micros(float(value))
        return None if micros is None else (micros, True)


_MISSING = object()


def _reject_constant(name: str) -> None:
    raise ValueError(f"invalid JSON constant {name}")


def _first_key(obj: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in obj:
            return obj[key]
    return _MISSING


class _Counters:
    __slots__ = ("lines", "out_of_range", "records", "tz_aware", "unparsed", "untimed")

    def __init__(self) -> None:
        self.lines = 0
        self.records = 0
        self.unparsed = 0
        self.out_of_range = 0
        self.untimed = 0
        self.tz_aware = False


def _open(path: str) -> tuple[IO[bytes], int]:
    if path == "-":
        return sys.stdin.buffer, 0
    try:
        file_path = Path(path)
        size = file_path.stat().st_size
        with file_path.open("rb") as probe:
            magic = probe.read(4)
        if magic[:2] == b"\x1f\x8b":
            return cast("IO[bytes]", gzip.open(file_path, "rb")), size
        if magic == b"\x28\xb5\x2f\xfd":
            raise SourceError(f"{path!r} is zstd-compressed; the reference engine cannot read it")
        return file_path.open("rb"), size
    except OSError as error:
        raise read_error(path, error) from error


def _lines(stream: IO[bytes]) -> Iterator[bytes]:
    window = MAX_LINE_BYTES + 2
    while raw := stream.readline(window):
        if raw.endswith(b"\n"):
            line = raw[:-1]
        else:
            line = raw
            while len(raw) == window and not raw.endswith(b"\n"):
                raw = stream.readline(window)
        yield (line[:-1] if line.endswith(b"\r") else line)[:MAX_LINE_BYTES]


def _scan(
    path: str,
    parser: RecordParser,
    counters: _Counters,
    on_record: Callable[[str, int | None, int | None], None],
    tick: Callable[[int], None],
    window: tuple[int | None, int | None] = (None, None),
) -> int:
    since, until = window
    bounded = since is not None or until is not None
    stream, size = _open(path)
    record_first = ""
    record_rest = ""
    record_size = 0
    open_record = False
    consumed = 0
    last_tick = 0

    def emit(first: str, rest: str) -> None:
        parsed = parser.parse(first, rest)
        if parsed is None:
            counters.unparsed += 1
            return
        message, timestamp, tz_aware, level = parsed
        if bounded:
            if timestamp is None:
                counters.untimed += 1
                return
            if (since is not None and timestamp < since) or (until is not None and timestamp >= until):
                counters.out_of_range += 1
                return
        counters.records += 1
        counters.tz_aware = counters.tz_aware or tz_aware
        on_record(message, timestamp, level)

    try:
        for line in _lines(stream):
            consumed += len(line) + 1
            text = line.decode("utf-8", "replace")
            blank = not line.strip(_ASCII_WS)
            if parser.multiline:
                if blank:
                    counters.lines += 1
                elif parser.starts_record(text):
                    if open_record:
                        emit(record_first, record_rest)
                    counters.lines += 1
                    record_first, record_rest, record_size, open_record = text, "", len(line), True
                elif open_record:
                    counters.lines += 1
                    if record_size < MAX_RECORD_BYTES:
                        record_rest += "\n" + text
                        record_size += 1 + len(line)
                else:
                    counters.lines += 1
                    counters.unparsed += 1
            else:
                counters.lines += 1
                if not blank:
                    emit(text, "")
            if consumed - last_tick >= _TICK_BYTES:
                tick(consumed - last_tick)
                last_tick = consumed
        if open_record:
            emit(record_first, record_rest)
    except OSError as error:
        raise read_error(path, error) from error
    finally:
        if stream is not sys.stdin.buffer:
            stream.close()
    if consumed > last_tick:
        tick(consumed - last_tick)
    return size


class PythonEngine:
    """The reference engine; always sequential.

    Attributes:
        name: ``python``.
    """

    name = "python"

    def mine(self, request: MineRequest, progress: ProgressCallback | None = None) -> MiningResult:
        """Mine ``request`` with the reference implementation.

        Args:
            request: What to mine.
            progress: Optional progress callback.

        Returns:
            Templates with per-run statistics.
        """
        started = time.perf_counter()
        if request.state is not None:
            raise EngineError(
                "state files need the native engine; the pure-Python engine cannot load or save them yet",
                hint="install a wheel with the native extension, or leave out the state options",
            )
        if request.windows and len(request.windows) != len(request.runs):
            raise ConfigError("there must be one time window per run")
        parser = RecordParser(request.format)
        masker = Masker(request.mining.masks)
        splitter = re.compile("[^" + re.escape(request.mining.delimiters) + "]+")
        n_runs = len(request.runs)
        miner = Miner(request.mining, n_runs)
        tick = progress or (lambda _n: None)
        trained: list[tuple[_Counters, int]] = []
        for run, files in enumerate(request.runs):
            counters = _Counters()
            total_bytes = 0
            window = request.windows[run] if request.windows else (None, None)

            def on_record(message: str, timestamp: int | None, level: int | None, run: int = run) -> None:
                tokens = splitter.findall(masker.mask(message))
                miner.add(run, tokens, message, timestamp, level)

            for path in files:
                total_bytes += _scan(path, parser, counters, on_record, tick, window)
            trained.append((counters, total_bytes))
        mined = time.perf_counter()
        recounted = time.perf_counter()
        if request.recount:
            recount = Recount(n_runs)
            for run, files in enumerate(request.runs):

                def on_recount(message: str, timestamp: int | None, level: int | None, run: int = run) -> None:
                    tokens = splitter.findall(masker.mask(message))
                    recount.record(miner, run, tokens, message, timestamp, level)

                window = request.windows[run] if request.windows else (None, None)
                for path in files:
                    _scan(path, parser, _Counters(), on_recount, tick, window)
            recounted = time.perf_counter()
            templates, overflowed = miner.freeze_recounted(recount)
        else:
            overflowed = list(miner.overflowed)
            templates = miner.freeze()
        done = time.perf_counter()
        infos = [
            RunInfo(
                files=len(request.runs[run]),
                lines=counters.lines,
                records=counters.records,
                unparsed=counters.unparsed,
                out_of_range=counters.out_of_range,
                untimed=counters.untimed,
                bytes=total_bytes,
                tz_aware=counters.tz_aware,
                overflowed=overflowed[run],
            )
            for run, (counters, total_bytes) in enumerate(trained)
        ]
        metrics = RunMetrics(
            engine="python",
            strategy="sequential",
            threads=1,
            chunks=sum(len(files) for files in request.runs),
            wall_total_s=done - started,
            wall_mine_s=mined - started,
            wall_merge_s=0.0,
            wall_recount_s=recounted - mined,
            wall_freeze_s=done - recounted,
        )
        return MiningResult(
            runs=tuple(infos), templates=TemplateTable.from_stats(templates, len(request.runs)), metrics=metrics
        )
