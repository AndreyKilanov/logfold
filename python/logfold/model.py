"""Public result model: immutable dataclasses returned by :func:`logfold.analyze` and :func:`logfold.diff`."""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from logfold.config import DiffConfig
from logfold.errors import ConfigError, NoLevelsError
from logfold.ext import registry
from logfold.ext.files import check_appendable, write_text
from logfold.levels import LEVEL_NAMES, at_least, normalize_level
from logfold.model_run import ResultMeta, RunMetrics, RunSummary, Unmatched
from logfold.model_values import TemplateValueChanges, ValueStats

SCHEMA_VERSION = 1

__all__ = [
    "SCHEMA_VERSION",
    "AnalysisResult",
    "DiffEntry",
    "DiffResult",
    "Parameter",
    "ResultMeta",
    "RunMetrics",
    "RunSummary",
    "Template",
    "TemplateMatch",
    "Unmatched",
]


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
        values: The distributions of the values at the variable positions, for a template that ``analyze(values=True)``
            tracked (one of the most frequent); ``None`` otherwise.
    """

    id: str
    text: str
    count: int
    first_seen: datetime | None
    last_seen: datetime | None
    example: str | None
    level: str | None
    levels: Mapping[str, int]
    values: tuple[ValueStats, ...] | None = None


@dataclass(frozen=True, slots=True)
class Parameter:
    """A value that a message gave to a variable position of a template.

    Attributes:
        position: Index of the token in the template.
        name: The name of the masking rule that matched the value (``num``, ``ip``, ...), or ``*`` for a position
            that the miner generalized.
        value: The text as it was written in the message, not the masked token.
    """

    position: int
    name: str
    value: str


@dataclass(frozen=True, slots=True)
class TemplateMatch:
    """The template that a record was assigned to by :meth:`logfold.Miner.match`.

    Attributes:
        id: The identifier of the template, the first 16 hex digits of ``sha256(text)``.
        text: The text of the template as the miner holds it now; it is the ``text`` of the same template in
            :meth:`logfold.Miner.result`.
    """

    id: str
    text: str


def _write(path: str | os.PathLike[str], text: str) -> None:
    write_text(path, text)


def _save(
    result: AnalysisResult | DiffResult,
    path: str | os.PathLike[str],
    reporter: str | None,
    options: dict[str, object],
    append: bool,
) -> str:
    name = reporter if reporter is not None else registry.reporter_for_suffix(path)
    if append:
        check_appendable(name)
    text = result.render(name, **options)
    if not isinstance(text, str):
        raise ConfigError(f"reporter {name!r} returned {type(text).__name__}, expected text")
    write_text(path, text, append)
    return text


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

    @property
    def levels(self) -> Mapping[str, int]:
        """Records per level name over all templates: only levels that occurred, least severe first."""
        totals: dict[str, int] = {}
        for template in self.templates:
            for name, count in template.levels.items():
                totals[name] = totals.get(name, 0) + count
        return {name: totals[name] for name in LEVEL_NAMES if totals.get(name)}

    def filter(self, *, min_level: str | None = None, min_count: int | None = None) -> AnalysisResult:
        """Keep only some templates; the run counters, metrics and meta stay as they were.

        Args:
            min_level: Keep templates whose most severe level is at least this one (``TRACE`` to ``FATAL``, any case).
                A template without a level is dropped.
            min_count: Keep templates with at least this many records.

        Returns:
            A new result with the kept templates, most frequent first.

        Raises:
            ConfigError: If ``min_level`` is not a level name.
            NoLevelsError: If ``min_level`` is given and no template has a level, which means the format has none.
        """
        kept = self.templates
        if min_level is not None:
            level = normalize_level(min_level)
            if kept and all(template.level is None for template in kept):
                raise NoLevelsError(self.meta.format)
            kept = tuple(template for template in kept if at_least(template.level, level))
        if min_count is not None:
            kept = tuple(template for template in kept if template.count >= min_count)
        return dataclasses.replace(self, templates=kept)

    def render(self, reporter: str, **options: object) -> str:
        """Render with a registered reporter.

        Args:
            reporter: Reporter name, for example ``json``.
            **options: Reporter options.

        Returns:
            The rendered text.
        """
        return registry.render(self, reporter, **options)

    def save(
        self, path: str | os.PathLike[str], reporter: str | None = None, *, append: bool = False, **options: object
    ) -> str:
        """Render with a reporter and write the text to a file.

        Args:
            path: Destination file (UTF-8).
            reporter: Reporter name; when ``None`` the suffix of ``path`` selects it (``.html``, ``.json``, ``.txt``,
                ``.md`` or ``.csv``, see :data:`logfold.ext.registry.SUFFIX_REPORTERS`).
            append: Add the text to the end of the file (creating it) after a blank line, instead of replacing the
                file; for text and Markdown reports, for example to build ``$GITHUB_STEP_SUMMARY`` from several steps.
            **options: Reporter options.

        Returns:
            The rendered text.

        Raises:
            UnknownSuffixError: If no reporter is named and the suffix selects none.
            ConfigError: If the reporter is unknown or does not support this kind of result, or ``append`` is used
                with a report that is a whole document (``html``, ``json``, ``csv``).
            OSError: If the file cannot be written.
        """
        return _save(self, path, reporter, options, append)

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
        score: G statistic of the change of the share, for ``changed`` entries; ``None`` for new and disappeared ones.
        p_value: Probability of a change at least this large by chance, for ``changed`` entries.
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
    score: float | None = None
    p_value: float | None = None


@dataclass(frozen=True, slots=True)
class DiffResult:
    """Result of :func:`logfold.diff`.

    Attributes:
        new_templates: Present after, absent before; most frequent first.
        disappeared: Present before, absent after; most frequent first.
        changed: Present in both with a share ratio of at least ``threshold_ratio`` and a p-value of at most
            ``significance``; largest score first.
        unchanged: Number of templates present in both runs without a significant change.
        before: Counters of the first run.
        after: Counters of the second run.
        config: Comparison parameters.
        metrics: Execution facts.
        meta: Provenance.
        warnings: Human readable warnings.
        value_changes: With ``diff(new_values=True)``: for the templates that both runs have, the variable positions
            whose values are new or gone (empty when none differ); ``None`` when it was not asked for.
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
    value_changes: tuple[TemplateValueChanges, ...] | None = None

    @property
    def new_alerts(self) -> tuple[DiffEntry, ...]:
        """New templates whose most severe level is WARN or higher."""
        return tuple(entry for entry in self.new_templates if entry.level in ("WARN", "ERROR", "FATAL"))

    def filter(self, *, min_level: str | None = None) -> DiffResult:
        """Keep only the new, disappeared and changed templates at or above a level.

        ``unchanged``, the run counters, metrics and meta stay as they were. Gates such as ``new_alerts`` then see the
        filtered lists.

        Args:
            min_level: Keep entries whose most severe level is at least this one (``TRACE`` to ``FATAL``, any case).
                An entry without a level is dropped.

        Returns:
            A new result with the kept entries.

        Raises:
            ConfigError: If ``min_level`` is not a level name.
            NoLevelsError: If ``min_level`` is given, there are entries and none has a level.
        """
        if min_level is None:
            return self
        level = normalize_level(min_level)
        listed = (*self.new_templates, *self.disappeared, *self.changed)
        if listed and all(entry.level is None for entry in listed):
            raise NoLevelsError(self.meta.format)

        def keep(entries: tuple[DiffEntry, ...]) -> tuple[DiffEntry, ...]:
            return tuple(entry for entry in entries if at_least(entry.level, level))

        return dataclasses.replace(
            self,
            new_templates=keep(self.new_templates),
            disappeared=keep(self.disappeared),
            changed=keep(self.changed),
            value_changes=None
            if self.value_changes is None
            else tuple(item for item in self.value_changes if at_least(item.level, level)),
        )

    def render(self, reporter: str, **options: object) -> str:
        """Render with a registered reporter.

        Args:
            reporter: Reporter name, for example ``json``.
            **options: Reporter options.

        Returns:
            The rendered text.
        """
        return registry.render(self, reporter, **options)

    def save(
        self, path: str | os.PathLike[str], reporter: str | None = None, *, append: bool = False, **options: object
    ) -> str:
        """Render with a reporter and write the text to a file.

        Args:
            path: Destination file (UTF-8).
            reporter: Reporter name; when ``None`` the suffix of ``path`` selects it (``.html``, ``.json``, ``.txt``,
                ``.md`` or ``.csv``, see :data:`logfold.ext.registry.SUFFIX_REPORTERS`).
            append: Add the text to the end of the file (creating it) after a blank line, instead of replacing the
                file; for text and Markdown reports, for example to build ``$GITHUB_STEP_SUMMARY`` from several steps.
            **options: Reporter options.

        Returns:
            The rendered text.

        Raises:
            UnknownSuffixError: If no reporter is named and the suffix selects none.
            ConfigError: If the reporter is unknown or does not support this kind of result, or ``append`` is used
                with a report that is a whole document (``html``, ``json``, ``csv``).
            OSError: If the file cannot be written.
        """
        return _save(self, path, reporter, options, append)

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
