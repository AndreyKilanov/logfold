"""The counters and provenance of a run: the parts of a result that every kind of result carries."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Unmatched:
    """The records of a run that belong to no template of the saved state it was matched against.

    Attributes:
        records: Number of records.
        by_length: ``(token count, records)`` pairs sorted by token count; a message is cut into tokens after masking.
            The text of the records is not kept.
    """

    records: int
    by_length: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Counters of one analyzed run.

    Attributes:
        name: Input paths joined with a comma.
        files: Number of input files.
        lines: Physical lines read, blank ones included.
        records: Parsed records.
        unparsed: Lines that did not become part of a record.
        bytes: Total size of the inputs on disk.
        tz_aware: ``True`` when timestamps carried a time zone; naive timestamps are interpreted as UTC.
        overflowed: ``True`` when ``max_templates`` was reached and some records were pooled into overflow templates.
        out_of_range: Records parsed but left out because their timestamp is outside the time window.
        untimed: Records parsed but left out because they have no timestamp and a time window was set.
        unmatched: Set by :func:`logfold.match`: the records that belong to no template of the state; ``None`` when the
            run was mined.
        evicted: Templates that were dropped to make room for new ones (``on_full='evict'``); their counts are in the
            catch-all templates, so the counts of the templates still add up to ``records``.
    """

    name: str
    files: int
    lines: int
    records: int
    unparsed: int
    bytes: int
    tz_aware: bool
    overflowed: bool
    out_of_range: int = 0
    untimed: int = 0
    unmatched: Unmatched | None = None
    evicted: int = 0

    @property
    def unparsed_ratio(self) -> float:
        """Share of lines that were not parsed (0 when there are no lines)."""
        return self.unparsed / self.lines if self.lines else 0.0


@dataclass(frozen=True, slots=True)
class RunMetrics:
    """Execution facts of a call.

    Attributes:
        engine: ``native`` or ``python``.
        strategy: ``sequential`` or ``chunked``.
        threads: Worker threads used.
        chunks: Planned chunks.
        wall_total_s: Wall time of the whole engine call.
        wall_mine_s: Wall time of reading, parsing and mining.
        wall_merge_s: Time spent merging chunk trees.
        wall_recount_s: Time spent re-assigning records to the finished tree (0 without recount).
        wall_freeze_s: Time spent freezing the result.
    """

    engine: str
    strategy: str
    threads: int
    chunks: int
    wall_total_s: float
    wall_mine_s: float
    wall_merge_s: float
    wall_recount_s: float
    wall_freeze_s: float


@dataclass(frozen=True, slots=True)
class ResultMeta:
    """Provenance of a result.

    Attributes:
        schema_version: Version of the JSON schema of the result.
        algo_version: Version of the algorithm contract.
        logfold_version: Version of the library.
        config_hash: Fingerprint of masks and mining parameters; results with different hashes may not be comparable.
        format: Name of the log format used.
        degraded: Always ``False``; kept for the saved results and the JSON schema of the time of the reference engine.
    """

    schema_version: int
    algo_version: int
    logfold_version: str
    config_hash: str
    format: str
    degraded: bool
