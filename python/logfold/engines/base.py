"""Engine port: the contract between the public API and the code that mines templates.

An engine receives plain data (:class:`MineRequest`) and returns plain data (:class:`MiningResult`). The native Rust
engine and the pure-Python reference engine implement the same contract and must agree exactly for the sequential
strategy (see ``docs/ALGORITHM.md``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from logfold.config import MiningConfig
from logfold.ext.formats import FormatSpec
from logfold.levels import LEVEL_NAMES, summarize_levels
from logfold.model import RunMetrics


@dataclass(frozen=True, slots=True)
class StateRequest:
    """The state files of a run: the state to continue from and the state to write (see ADR-011).

    Attributes:
        load: Path of a state file to continue from, or ``None``.
        save: Path of the state file to write after the run, or ``None``.
        format: ``json`` or ``binary``.
        config_hash: Fingerprint of the mining parameters and the masks; a loaded state must carry the same one.
        masks: Identity of the mask set, for the header of a saved state.
        logfold_version: Version of this logfold, for the header of a saved state.
        log_format: Name of the log format, for the header of a saved state.
    """

    load: str | None
    save: str | None
    format: str
    config_hash: str
    masks: str
    logfold_version: str
    log_format: str


@dataclass(frozen=True, slots=True)
class MineRequest:
    """Everything an engine needs to mine one or more runs.

    Attributes:
        runs: Runs, each an ordered tuple of input paths (``-`` is standard input).
        format: Declarative log format.
        mining: Miner and masking parameters.
        strategy: ``sequential``, ``chunked`` or ``adaptive`` (chunked unless the first chunk is too diverse; already
            resolved, never ``auto``).
        threads: Worker threads for ``chunked``; ``None`` means all cores.
        chunk_bytes: Chunk size for ``chunked``.
        warm_start: ``chunked`` only: start every chunk but the first from a copy of the tree of the first.
        recount: Re-assign every record to the finished tree after training; gives consistent assignments
            across runs at the cost of a second pass.
        state: State files to load and save, or ``None``. Only the sequential strategy continues a loaded state.
        windows: One time window per run, or empty for none. A window is ``(since, until)`` in microseconds since the
            Unix epoch, each bound ``None`` when open: a record is mined when ``since <= timestamp < until``. A record
            without a timestamp is left out of a run whose window has a bound.
    """

    runs: tuple[tuple[str, ...], ...]
    format: FormatSpec
    mining: MiningConfig
    strategy: str = "sequential"
    threads: int | None = None
    chunk_bytes: int = 64 << 20
    warm_start: bool = False
    recount: bool = False
    windows: tuple[tuple[int | None, int | None], ...] = ()
    state: StateRequest | None = None


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
class RunColumns:
    """Statistics of one run for every template, as parallel columns.

    Attributes:
        counts: Records per template.
        first: Earliest timestamp in microseconds, or ``None``.
        last: Latest timestamp in microseconds, or ``None``.
        levels: Record counts per level name, only for the levels that occurred, in order of severity.
        level: Most severe level that occurred, or ``None``.
        examples: Raw message of the first record, or ``None`` when the run has none.
    """

    counts: Sequence[int]
    first: Sequence[int | None]
    last: Sequence[int | None]
    levels: Sequence[Mapping[str, int]]
    level: Sequence[str | None]
    examples: Sequence[str | None]


@dataclass(frozen=True, slots=True)
class TemplateTable:
    """The templates of a result as columns, which are cheap to build and to scan.

    The table also behaves as a sequence of :class:`TemplateStats` rows, built on access, for code that wants one
    template at a time.

    Attributes:
        ids: ``sha256(text)[:16]`` of every template.
        texts: Template texts.
        runs: Statistics per run, in run order.
    """

    ids: Sequence[str]
    texts: Sequence[str]
    runs: tuple[RunColumns, ...]

    def __len__(self) -> int:
        """Return the number of templates."""
        return len(self.ids)

    def __getitem__(self, index: int) -> TemplateStats:
        """Return the row of one template.

        Args:
            index: Position of the template.

        Returns:
            The template with the statistics of every run.

        Raises:
            TypeError: If ``index`` is not an integer (slices are not supported).
        """
        if not isinstance(index, int):
            raise TypeError(f"template indices must be integers, not {type(index).__name__}")
        runs = tuple(
            RunStatsData(
                count=run.counts[index],
                first=run.first[index],
                last=run.last[index],
                levels=tuple(run.levels[index].get(name, 0) for name in LEVEL_NAMES),
                example=run.examples[index],
            )
            for run in self.runs
        )
        return TemplateStats(id=self.ids[index], text=self.texts[index], runs=runs)

    def __iter__(self) -> Iterator[TemplateStats]:
        """Iterate over the rows."""
        return (self[index] for index in range(len(self)))

    @classmethod
    def from_stats(cls, templates: Sequence[TemplateStats], runs: int) -> TemplateTable:
        """Build the table from rows.

        Args:
            templates: Templates with statistics for ``runs`` runs.
            runs: Number of runs.

        Returns:
            The same templates as columns.
        """
        columns = []
        for run in range(runs):
            stats = [template.runs[run] for template in templates]
            summarized = [summarize_levels(item.levels) for item in stats]
            columns.append(
                RunColumns(
                    counts=[item.count for item in stats],
                    first=[item.first for item in stats],
                    last=[item.last for item in stats],
                    levels=[levels for _, levels in summarized],
                    level=[level for level, _ in summarized],
                    examples=[item.example for item in stats],
                )
            )
        return cls(ids=[t.id for t in templates], texts=[t.text for t in templates], runs=tuple(columns))


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
        out_of_range: Records left out because their timestamp is outside the time window.
        untimed: Records left out because they have no timestamp and the time window has a bound.
    """

    files: int
    lines: int
    records: int
    unparsed: int
    bytes: int
    tz_aware: bool
    overflowed: bool
    out_of_range: int = 0
    untimed: int = 0


@dataclass(frozen=True, slots=True)
class MiningResult:
    """Output of an engine.

    Attributes:
        runs: Per-run counters.
        templates: Unique templates sorted by total count descending, then text ascending, as columns.
        metrics: Execution facts.
    """

    runs: tuple[RunInfo, ...]
    templates: TemplateTable
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
