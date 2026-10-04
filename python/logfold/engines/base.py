"""Engine port: the contract between the public API and the code that mines templates.

An engine receives plain data (:class:`MineRequest`) and returns plain data (:class:`MiningResult`). The native Rust
engine and the pure-Python reference engine implement the same contract and must agree exactly for the sequential
strategy (see ``docs/ALGORITHM.md``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from logfold.config import MiningConfig
from logfold.ext.formats import FormatSpec
from logfold.model import RunMetrics


@dataclass(frozen=True, slots=True)
class MineRequest:
    """Everything an engine needs to mine one or more runs.

    Attributes:
        runs: Runs, each an ordered tuple of input paths (``-`` is standard input).
        format: Declarative log format.
        mining: Miner and masking parameters.
        strategy: ``sequential`` or ``chunked`` (already resolved, never ``auto``).
        threads: Worker threads for ``chunked``; ``None`` means all cores.
        chunk_bytes: Chunk size for ``chunked``.
        recount: Re-assign every record to the finished tree after training; gives consistent assignments
            across runs at the cost of a second pass.
    """

    runs: tuple[tuple[str, ...], ...]
    format: FormatSpec
    mining: MiningConfig
    strategy: str = "sequential"
    threads: int | None = None
    chunk_bytes: int = 64 << 20
    recount: bool = False


@dataclass(frozen=True, slots=True)
class RunStatsData:
    """Statistics of one template within one run.

    Attributes:
        count: Records.
        first: Earliest timestamp in microseconds, or ``None``.
        last: Latest timestamp in microseconds, or ``None``.
        levels: Counts per level rank (TRACE..FATAL).
        example: Raw message of the first record, or ``None`` when the run has none.
    """

    count: int
    first: int | None
    last: int | None
    levels: tuple[int, ...]
    example: str | None


@dataclass(frozen=True, slots=True)
class TemplateStats:
    """A frozen template with per-run statistics.

    Attributes:
        id: ``sha256(text)[:16]``.
        text: Template text.
        runs: Statistics for every run, in run order.
    """

    id: str
    text: str
    runs: tuple[RunStatsData, ...]

    @property
    def total(self) -> int:
        """Total records over all runs."""
        return sum(run.count for run in self.runs)


@dataclass(frozen=True, slots=True)
class RunInfo:
    """Counters of one run.

    Attributes:
        files: Number of input files.
        lines: Non-blank physical lines.
        records: Parsed records.
        unparsed: Lines that did not become part of a record.
        bytes: Total size of the inputs on disk.
        tz_aware: True when any timestamp carried a zone.
        overflowed: True when records were pooled into overflow templates.
    """

    files: int
    lines: int
    records: int
    unparsed: int
    bytes: int
    tz_aware: bool
    overflowed: bool


@dataclass(frozen=True, slots=True)
class MiningResult:
    """Output of an engine.

    Attributes:
        runs: Per-run counters.
        templates: Unique templates sorted by total count descending, then text ascending.
        metrics: Execution facts.
    """

    runs: tuple[RunInfo, ...]
    templates: tuple[TemplateStats, ...]
    metrics: RunMetrics


ProgressCallback = Callable[[int], None]


class Engine(Protocol):
    """Mines templates from one or more runs.

    Attributes:
        name: ``native`` or ``python``.
    """

    name: str

    def mine(self, request: MineRequest, progress: ProgressCallback | None = None) -> MiningResult:
        """Mine ``request``.

        Args:
            request: What to mine and how.
            progress: Optional callback receiving the number of input bytes consumed since the previous call.

        Returns:
            Templates with per-run statistics.
        """
        ...
