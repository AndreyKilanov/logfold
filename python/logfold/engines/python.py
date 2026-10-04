"""Pure-Python reference engine.

A deliberately simple, slow implementation of ``docs/ALGORITHM.md``. It is the oracle that the native engine is tested
against and the fallback when the native extension is unavailable. It always runs the sequential strategy.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import math
import re
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any, cast

from logfold.config import MiningConfig
from logfold.engines import _timeparse as tp
from logfold.engines.base import MineRequest, MiningResult, ProgressCallback, RunInfo, RunStatsData, TemplateStats
from logfold.errors import FormatError, SourceError
from logfold.ext.formats import FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.masks import Masker
from logfold.model import RunMetrics

WILDCARD = "<*>"
MAX_EXAMPLE_BYTES = 2000
_ASCII_WS = b" \t\n\x0c\r"
_TICK_BYTES = 16 << 20
_DIGIT = re.compile("[0-9]")

ParsedRecord = tuple[str, "int | None", bool, "int | None"]


def _truncate_example(message: str) -> str:
    encoded = message.encode("utf-8", "replace")
    if len(encoded) <= MAX_EXAMPLE_BYTES:
        return message
    return encoded[:MAX_EXAMPLE_BYTES].decode("utf-8", "ignore")


class _Stats:
    __slots__ = ("count", "example", "first", "last", "levels")

    def __init__(self) -> None:
        self.count = 0
        self.first: int | None = None
        self.last: int | None = None
        self.levels = [0] * len(tp.LEVEL_NAMES)
        self.example: str | None = None

    def record(self, message: str, timestamp: int | None, level: int | None) -> None:
        self.count += 1
        if timestamp is not None:
            self.first = timestamp if self.first is None else min(self.first, timestamp)
            self.last = timestamp if self.last is None else max(self.last, timestamp)
        if level is not None:
            self.levels[level] += 1
        if self.example is None:
            self.example = _truncate_example(message)

    def absorb(self, other: _Stats) -> None:
        self.count += other.count
        if other.first is not None:
            self.first = other.first if self.first is None else min(self.first, other.first)
        if other.last is not None:
            self.last = other.last if self.last is None else max(self.last, other.last)
        for index, value in enumerate(other.levels):
            self.levels[index] += value
        if self.example is None:
            self.example = other.example


class _Cluster:
    __slots__ = ("stats", "tokens")

    def __init__(self, tokens: list[str], n_runs: int) -> None:
        self.tokens = tokens
        self.stats = [_Stats() for _ in range(n_runs)]


class _Node:
    __slots__ = ("children", "clusters")

    def __init__(self) -> None:
        self.children: dict[str, _Node] = {}
        self.clusters: list[int] = []


class _Recount:
    """Statistics of records assigned to the clusters of a finished tree (``docs/ALGORITHM.md`` §9)."""

    def __init__(self, n_runs: int) -> None:
        self._n_runs = n_runs
        self.stats: dict[int, list[_Stats]] = {}
        self.unmatched: dict[int, list[_Stats]] = {}

    def record(
        self, miner: _Miner, run: int, tokens: list[str], message: str, timestamp: int | None, level: int | None
    ) -> None:
        index = miner.assign(tokens)
        if index is not None:
            slot = self.stats.setdefault(index, [_Stats() for _ in range(self._n_runs)])
        else:
            slot = self.unmatched.setdefault(len(tokens), [_Stats() for _ in range(self._n_runs)])
        slot[run].record(message, timestamp, level)


class _Miner:
    """Drain-compatible template tree following ``docs/ALGORITHM.md`` §4."""

    def __init__(self, config: MiningConfig, n_runs: int) -> None:
        self._depth = config.depth
        self._threshold = math.floor(config.sim_th * 1_000_000.0 + 0.5)
        self._max_children = config.max_children
        self._max_templates = config.max_templates
        self._n_runs = n_runs
        self._length_nodes: dict[int, _Node] = {}
        self.clusters: list[_Cluster] = []
        self.overflow: dict[int, _Cluster] = {}
        self.overflowed = [False] * n_runs
        self._by_length: dict[int, list[int]] = {}

    def _layers(self, n: int) -> int:
        return 0 if n == 0 else min(self._depth - 3, n - 1)

    def _search(self, tokens: list[str]) -> _Node | None:
        node = self._length_nodes.get(len(tokens))
        if node is None:
            return None
        for layer in range(self._layers(len(tokens))):
            token = tokens[layer]
            children = node.children
            nxt = children.get(WILDCARD) if _DIGIT.search(token) else children.get(token) or children.get(WILDCARD)
            if nxt is None:
                return None
            node = nxt
        return node

    def _find_match(self, tokens: list[str]) -> _Cluster | None:
        leaf = self._search(tokens)
        if leaf is None:
            return None
        index = self._best_in(leaf.clusters, tokens)
        return None if index is None else self.clusters[index]

    def _best_in(self, candidates: list[int], tokens: list[str]) -> int | None:
        best: tuple[int, int, int] | None = None
        for index in candidates:
            total, params = _score(self.clusters[index].tokens, tokens)
            if best is None or total > best[1] or (total == best[1] and params > best[2]):
                best = (index, total, params)
        if best is None:
            return None
        index, total, _ = best
        return index if total * 1_000_000 >= self._threshold * len(tokens) else None

    def _insert_path(self, tokens: list[str]) -> _Node:
        n = len(tokens)
        node = self._length_nodes.get(n)
        if node is None:
            node = self._length_nodes[n] = _Node()
        for layer in range(self._layers(n)):
            token = tokens[layer]
            key = WILDCARD if _DIGIT.search(token) else token
            child = node.children.get(key)
            if child is None:
                size = len(node.children)
                if key == WILDCARD:
                    create: str | None = WILDCARD
                elif WILDCARD in node.children:
                    create = key if size < self._max_children else None
                elif size + 1 < self._max_children:
                    create = key
                else:
                    create = WILDCARD
                if create is None:
                    child = node.children[WILDCARD]
                else:
                    child = node.children[create] = _Node()
            node = child
        return node

    def _insert_cluster(self, cluster: _Cluster) -> None:
        if len(self.clusters) >= self._max_templates:
            length = len(cluster.tokens)
            for run, stats in enumerate(cluster.stats):
                if stats.count > 0:
                    self.overflowed[run] = True
            mine = self.overflow.get(length)
            if mine is None:
                pooled = _Cluster([WILDCARD] * length, self._n_runs)
                pooled.stats = cluster.stats
                self.overflow[length] = pooled
            else:
                for dst, src in zip(mine.stats, cluster.stats, strict=True):
                    dst.absorb(src)
            return
        leaf = self._insert_path(cluster.tokens)
        leaf.clusters.append(len(self.clusters))
        self._by_length.setdefault(len(cluster.tokens), []).append(len(self.clusters))
        self.clusters.append(cluster)

    def add(self, run: int, tokens: list[str], message: str, timestamp: int | None, level: int | None) -> None:
        cluster = self._find_match(tokens)
        if cluster is not None:
            _generalize(cluster, tokens)
            cluster.stats[run].record(message, timestamp, level)
            return
        created = _Cluster(list(tokens), self._n_runs)
        created.stats[run].record(message, timestamp, level)
        self._insert_cluster(created)

    def assign(self, tokens: list[str]) -> int | None:
        """Return the index of the cluster a message belongs to, or ``None`` when nothing matches."""
        leaf = self._search(tokens)
        if leaf is not None:
            index = self._best_in(leaf.clusters, tokens)
            if index is not None:
                return index
        return self._best_in(self._by_length.get(len(tokens), []), tokens)

    def freeze_recounted(self, recount: _Recount) -> tuple[list[TemplateStats], list[bool]]:
        """Freeze with statistics from a recount instead of those gathered while training."""
        flags = list(self.overflowed)
        ordered: list[_Cluster] = []
        for index, cluster in enumerate(self.clusters):
            stats = recount.stats.get(index)
            if stats is not None:
                holder = _Cluster(cluster.tokens, self._n_runs)
                holder.stats = stats
                ordered.append(holder)
        for length in sorted(recount.unmatched):
            stats = recount.unmatched[length]
            for run, item in enumerate(stats):
                if item.count > 0:
                    flags[run] = True
            holder = _Cluster([WILDCARD] * length, self._n_runs)
            holder.stats = stats
            ordered.append(holder)
        return self._freeze(ordered), flags

    def freeze(self) -> list[TemplateStats]:
        ordered = list(self.clusters)
        ordered.extend(self.overflow[length] for length in sorted(self.overflow))
        return self._freeze(ordered)

    def _freeze(self, ordered: list[_Cluster]) -> list[TemplateStats]:
        by_text: dict[str, _Cluster] = {}
        for cluster in ordered:
            text = " ".join(cluster.tokens)
            existing = by_text.get(text)
            if existing is None:
                holder = _Cluster([], self._n_runs)
                holder.stats = cluster.stats
                by_text[text] = holder
            else:
                for dst, src in zip(existing.stats, cluster.stats, strict=True):
                    dst.absorb(src)
        frozen = [
            TemplateStats(
                id=hashlib.sha256(text.encode("utf-8")).hexdigest()[:16],
                text=text,
                runs=tuple(RunStatsData(s.count, s.first, s.last, tuple(s.levels), s.example) for s in holder.stats),
            )
            for text, holder in by_text.items()
        ]
        frozen.sort(key=lambda t: (-t.total, t.text.encode("utf-8")))
        return frozen


def _score(template: list[str], tokens: list[str]) -> tuple[int, int]:
    exact = 0
    params = 0
    for t, m in zip(template, tokens, strict=True):
        if t == WILDCARD:
            params += 1
        elif t == m:
            exact += 1
    return exact, params


def _generalize(cluster: _Cluster, tokens: list[str]) -> None:
    template = cluster.tokens
    for position, token in enumerate(template):
        if token != WILDCARD and token != tokens[position]:
            template[position] = WILDCARD


class _Parser:
    """Parses records of a :class:`~logfold.ext.formats.FormatSpec` (``docs/ALGORITHM.md`` §1.2)."""

    def __init__(self, spec: FormatSpec) -> None:
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
        if isinstance(self._spec, RegexFormat):
            assert self._regex is not None
            return self._regex.search(line) is not None
        if isinstance(self._spec, PlainFormat):
            return self._record_start is not None and self._record_start.search(line) is not None
        return line.lstrip(" \t\n\x0c\r").startswith("{")

    def _time(self, text: str) -> tp.Parsed | None:
        return self._ts.parse(text) if self._ts is not None else tp.parse_iso(text)

    def parse(self, first: str, continuation: str) -> ParsedRecord | None:
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
    __slots__ = ("lines", "records", "tz_aware", "unparsed")

    def __init__(self) -> None:
        self.lines = 0
        self.records = 0
        self.unparsed = 0
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
        raise SourceError(f"cannot read {path!r}: {error}") from error


def _lines(stream: IO[bytes]) -> Iterator[bytes]:
    for raw in stream:
        line = raw[:-1] if raw.endswith(b"\n") else raw
        yield line[:-1] if line.endswith(b"\r") else line


def _scan(
    path: str,
    parser: _Parser,
    counters: _Counters,
    on_record: Callable[[str, int | None, int | None], None],
    tick: Callable[[int], None],
) -> int:
    stream, size = _open(path)
    record_first = ""
    record_rest = ""
    open_record = False
    consumed = 0
    last_tick = 0

    def emit(first: str, rest: str) -> None:
        parsed = parser.parse(first, rest)
        if parsed is None:
            counters.unparsed += 1
            return
        message, timestamp, tz_aware, level = parsed
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
                    record_first, record_rest, open_record = text, "", True
                elif open_record:
                    counters.lines += 1
                    record_rest += "\n" + text
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
        raise SourceError(f"cannot read {path!r}: {error}") from error
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
        parser = _Parser(request.format)
        masker = Masker(request.mining.masks)
        splitter = re.compile("[^" + re.escape(request.mining.delimiters) + "]+")
        n_runs = len(request.runs)
        miner = _Miner(request.mining, n_runs)
        tick = progress or (lambda _n: None)
        trained: list[tuple[_Counters, int]] = []
        for run, files in enumerate(request.runs):
            counters = _Counters()
            total_bytes = 0

            def on_record(message: str, timestamp: int | None, level: int | None, run: int = run) -> None:
                tokens = splitter.findall(masker.mask(message))
                miner.add(run, tokens, message, timestamp, level)

            for path in files:
                total_bytes += _scan(path, parser, counters, on_record, tick)
            trained.append((counters, total_bytes))
        mined = time.perf_counter()
        recounted = time.perf_counter()
        if request.recount:
            recount = _Recount(n_runs)
            for run, files in enumerate(request.runs):

                def on_recount(message: str, timestamp: int | None, level: int | None, run: int = run) -> None:
                    tokens = splitter.findall(masker.mask(message))
                    recount.record(miner, run, tokens, message, timestamp, level)

                for path in files:
                    _scan(path, parser, _Counters(), on_recount, tick)
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
        return MiningResult(runs=tuple(infos), templates=tuple(templates), metrics=metrics)
