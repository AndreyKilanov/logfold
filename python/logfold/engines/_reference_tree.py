"""Template tree of the pure-Python reference engine (``docs/ALGORITHM.md`` §4 and §9).

The tree, the per-run statistics and the recount pass. It reads no files and knows nothing about formats.
"""

from __future__ import annotations

import hashlib
import math
import re

from logfold.config import MiningConfig
from logfold.engines import _timeparse as tp
from logfold.engines.base import RunStatsData, TemplateStats

WILDCARD = "<*>"
MAX_EXAMPLE_BYTES = 2000
_DIGIT = re.compile("[0-9]")


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


class Recount:
    """Statistics of records assigned to the clusters of a finished tree (``docs/ALGORITHM.md`` §9)."""

    def __init__(self, n_runs: int) -> None:
        self._n_runs = n_runs
        self.stats: dict[int, list[_Stats]] = {}
        self.unmatched: dict[int, list[_Stats]] = {}

    def record(
        self, miner: Miner, run: int, tokens: list[str], message: str, timestamp: int | None, level: int | None
    ) -> None:
        index = miner.assign(tokens)
        if index is not None:
            slot = self.stats.setdefault(index, [_Stats() for _ in range(self._n_runs)])
        else:
            slot = self.unmatched.setdefault(len(tokens), [_Stats() for _ in range(self._n_runs)])
        slot[run].record(message, timestamp, level)


class Miner:
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

    def freeze_recounted(self, recount: Recount) -> tuple[list[TemplateStats], list[bool]]:
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
