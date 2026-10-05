"""Public result model: immutable dataclasses returned by :func:`logfold.analyze` and :func:`logfold.diff`."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from logfold.config import DiffConfig
from logfold.ext import registry

SCHEMA_VERSION = 1
LEVEL_NAMES = ("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def micros_to_datetime(micros: int | None, tz_aware: bool) -> datetime | None:
    """Convert microseconds since the Unix epoch to a ``datetime``.

    Args:
        micros: Microseconds, or ``None``.
        tz_aware: Return an aware UTC datetime when true, otherwise a naive one holding the same wall-clock time.

    Returns:
        The datetime, or ``None`` when ``micros`` is ``None``.
    """
    if micros is None:
        return None
    moment = _EPOCH + timedelta(microseconds=micros)
    return moment if tz_aware else moment.replace(tzinfo=None)


def micros_to_datetimes(values: Sequence[int | None], tz_aware: bool) -> list[datetime | None]:
    """Convert a column of microsecond timestamps; the column form of :func:`micros_to_datetime`.

    Args:
        values: Microseconds since the Unix epoch, or ``None``.
        tz_aware: Return aware UTC datetimes when true, otherwise naive ones holding the same wall-clock time.

    Returns:
        The datetimes, ``None`` where the value is ``None``.
    """
    epoch = _EPOCH if tz_aware else _EPOCH.replace(tzinfo=None)
    return [None if value is None else epoch + timedelta(microseconds=value) for value in values]


def datetime_to_micros(moment: datetime | None) -> int | None:
    """Convert a ``datetime`` to microseconds since the Unix epoch; the inverse of :func:`micros_to_datetime`.

    Args:
        moment: An aware datetime, or a naive one that is interpreted as UTC; ``None`` is allowed.

    Returns:
        Microseconds, or ``None`` when ``moment`` is ``None``.
    """
    if moment is None:
        return None
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return (aware - _EPOCH) // timedelta(microseconds=1)


def summarize_levels(counts: Sequence[int]) -> tuple[str | None, dict[str, int]]:
    """Summarize per-rank level counts.

    Args:
        counts: Record counts indexed by level rank (TRACE..FATAL).

    Returns:
        The most severe level that occurred (or ``None``) and a mapping of level name to count for levels that
        occurred.
    """
    levels = {LEVEL_NAMES[rank]: count for rank, count in enumerate(counts) if count > 0}
    most_severe = next((LEVEL_NAMES[rank] for rank in range(len(counts) - 1, -1, -1) if counts[rank] > 0), None)
    return most_severe, levels


@dataclass(frozen=True, slots=True)
class Template:
    """A log message template with statistics.

    Attributes:
        id: Stable identifier, the first 16 hex digits of ``sha256(text)``.
        text: Template text; variable parts are ``<*>`` or a mask token such as ``<IP>``.
        count: Number of records matching the template.
        first_seen: Earliest timestamp seen, or ``None`` when records carry none.
        last_seen: Latest timestamp seen, or ``None``.
        example: A raw message of the first matching record.
        level: Most severe level seen, or ``None``.
        levels: Record counts per level name (only levels that occurred).
    """

    id: str
    text: str
    count: int
    first_seen: datetime | None
    last_seen: datetime | None
    example: str | None
    level: str | None
    levels: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Counters of one analyzed run.

    Attributes:
        name: Input paths joined with a comma.
        files: Number of input files.
        lines: Non-blank physical lines read.
        records: Parsed records.
        unparsed: Lines that did not become part of a record.
        bytes: Total size of the inputs on disk.
        tz_aware: ``True`` when timestamps carried a time zone; naive timestamps are interpreted as UTC.
        overflowed: ``True`` when ``max_templates`` was reached and some records were pooled into overflow templates.
    """

    name: str
    files: int
    lines: int
    records: int
    unparsed: int
    bytes: int
    tz_aware: bool
    overflowed: bool

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
        degraded: ``True`` when the slow reference engine was used.
    """

    schema_version: int
    algo_version: int
    logfold_version: str
    config_hash: str
    format: str
    degraded: bool


def _write(path: str | os.PathLike[str], text: str) -> None:
    Path(path).write_text(text, encoding="utf-8")


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """Result of :func:`logfold.analyze`.

    Attributes:
        templates: All templates, most frequent first.
        run: Counters of the analyzed input.
        metrics: Execution facts.
        meta: Provenance.
        warnings: Human readable warnings (low parse rate, overflow, degraded engine).
    """

    templates: tuple[Template, ...]
    run: RunSummary
    metrics: RunMetrics
    meta: ResultMeta
    warnings: tuple[str, ...] = ()

    def top(self, n: int = 20) -> tuple[Template, ...]:
        """Return the ``n`` most frequent templates.

        Args:
            n: Number of templates.

        Returns:
            At most ``n`` templates, most frequent first.
        """
        return self.templates[: max(n, 0)]

    def render(self, reporter: str, **options: object) -> str:
        """Render with a registered reporter.

        Args:
            reporter: Reporter name, for example ``json``.
            **options: Reporter options.

        Returns:
            The rendered text.
        """
        return registry.render(self, reporter, **options)

    def to_json(self, path: str | os.PathLike[str] | None = None, **options: object) -> str:
        """Render as JSON and optionally write it to a file.

        Args:
            path: Destination file; nothing is written when ``None``.
            **options: Reporter options.

        Returns:
            The JSON text.
        """
        text = self.render("json", **options)
        if path is not None:
            _write(path, text)
        return text

    def to_html(self, path: str | os.PathLike[str] | None = None, **options: object) -> str:
        """Render as a self-contained HTML report and optionally write it to a file.

        Args:
            path: Destination file; nothing is written when ``None``.
            **options: Reporter options.

        Returns:
            The HTML document.
        """
        text = self.render("html", **options)
        if path is not None:
            _write(path, text)
        return text


@dataclass(frozen=True, slots=True)
class DiffEntry:
    """A template compared across two runs.

    Attributes:
        id: Identifier of the representative template.
        text: Representative template text (from the second run when present there).
        before_count: Records in the first run.
        after_count: Records in the second run.
        before_share: Share of the first run's records.
        after_share: Share of the second run's records.
        ratio: ``after_share / before_share``; ``None`` when either count is zero.
        level: Most severe level seen in the run(s) where the template occurs.
        levels: Level counts summed over both runs.
        example: Example message (from the second run when present there).
        first_seen: Earliest timestamp in the run used for ``example``.
        last_seen: Latest timestamp in the run used for ``example``.
    """

    id: str
    text: str
    before_count: int
    after_count: int
    before_share: float
    after_share: float
    ratio: float | None
    level: str | None
    levels: Mapping[str, int]
    example: str | None
    first_seen: datetime | None
    last_seen: datetime | None


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Result of :func:`logfold.diff`.

    Attributes:
        new_templates: Present after, absent before; most frequent first.
        disappeared: Present before, absent after; most frequent first.
        changed: Present in both with a share ratio of at least ``threshold_ratio``; largest change first.
        unchanged: Number of templates present in both runs without a significant change.
        before: Counters of the first run.
        after: Counters of the second run.
        config: Comparison parameters.
        metrics: Execution facts.
        meta: Provenance.
        warnings: Human readable warnings.
    """

    new_templates: tuple[DiffEntry, ...]
    disappeared: tuple[DiffEntry, ...]
    changed: tuple[DiffEntry, ...]
    unchanged: int
    before: RunSummary
    after: RunSummary
    config: DiffConfig
    metrics: RunMetrics
    meta: ResultMeta
    warnings: tuple[str, ...] = ()

    @property
    def new_alerts(self) -> tuple[DiffEntry, ...]:
        """New templates whose most severe level is WARN or higher."""
        return tuple(entry for entry in self.new_templates if entry.level in ("WARN", "ERROR", "FATAL"))

    def render(self, reporter: str, **options: object) -> str:
        """Render with a registered reporter.

        Args:
            reporter: Reporter name, for example ``json``.
            **options: Reporter options.

        Returns:
            The rendered text.
        """
        return registry.render(self, reporter, **options)

    def to_json(self, path: str | os.PathLike[str] | None = None, **options: object) -> str:
        """Render as JSON and optionally write it to a file.

        Args:
            path: Destination file; nothing is written when ``None``.
            **options: Reporter options.

        Returns:
            The JSON text.
        """
        text = self.render("json", **options)
        if path is not None:
            _write(path, text)
        return text

    def to_html(self, path: str | os.PathLike[str] | None = None, **options: object) -> str:
        """Render as a self-contained HTML report and optionally write it to a file.

        Args:
            path: Destination file; nothing is written when ``None``.
            **options: Reporter options.

        Returns:
            The HTML document.
        """
        text = self.render("html", **options)
        if path is not None:
            _write(path, text)
        return text
