"""``Miner``: a template miner that takes records as they come, instead of reading a file."""

from __future__ import annotations

import os
from collections.abc import Iterable

from logfold.api._common import (
    UNPARSED_WARNING_RATIO,
    PathLike,
    _apply_settings,
    _meta,
    _mining,
    _state_request,
    _templates,
)
from logfold.api.parameters import extract_parameters
from logfold.config import ExamplesMode, MiningConfig
from logfold.engines.base import MiningResult
from logfold.engines.live import LiveMiner
from logfold.errors import ConfigError
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.mask_selection import MaskSelection
from logfold.ext.masks import Masker
from logfold.formats import resolve_format
from logfold.model import AnalysisResult, Parameter, RunSummary, Template, TemplateMatch
from logfold.settings import Settings

STREAM_NAME = "stream"


class Miner:
    """A template miner that takes records in batches and keeps its templates between calls.

    A batch is one native call, so ``add_many`` is the fast path; ``add_log_message`` crosses the native boundary once
    per message and is meant for code that was written one message at a time. The result of a miner equals the result
    of ``analyze`` in sequential mode over the same records in the same order, whatever the sizes of the batches.

    The miner is safe to share between threads, and the native call releases the GIL. Records given by several threads
    are mined in the order in which the calls get the lock, so only a single feeder gives a repeatable result.

    Memory is bounded for any stream: a record is cut at 1 MiB, a line at 16 MiB, and the number of templates is limited
    by ``max_templates``; the text of a record is kept only as the example of its template.
    """

    def __init__(
        self,
        *,
        format: str | FormatSpec | Format | None = None,
        multiline: bool | None = None,
        depth: int | None = None,
        sim_th: float | None = None,
        max_children: int | None = None,
        max_templates: int | None = None,
        on_full: str | None = None,
        delimiters: str | None = None,
        masks: MaskSelection | None = None,
        mining: MiningConfig | None = None,
        load_state: PathLike | None = None,
        state_format: str = "json",
        examples: ExamplesMode = "raw",
        config: Settings | None = None,
    ) -> None:
        """Open a miner, empty or continuing from a saved state.

        Args:
            format: A registered name, ``regex:<pattern>``, a format specification or a ``Format`` object. The default
                is ``plain`` (the whole record is the message), also when the settings say ``auto``: a stream has no
                file to detect a format from, so ``auto`` named here is refused.
            multiline: Join continuation lines to the previous record (``add_lines`` only); ``None`` keeps the format's
                default.
            depth: Tree depth (default 4).
            sim_th: Similarity threshold (default 0.4).
            max_children: Maximum children per tree node (default 100).
            max_templates: Maximum number of templates before pooling or evicting (default 100000).
            on_full: ``pool`` (the default) or ``evict``: what happens to a new message shape when ``max_templates`` is
                reached; ``evict`` drops the least recently used templates and keeps learning, which a miner that runs
                for days needs. See :class:`~logfold.MiningConfig`.
            delimiters: The ASCII characters that separate tokens, replacing the default (space, tab, CR, LF); keep the
                whitespace in the string when you add a character, for example the default plus ``_`` or ``=``.
            masks: Rules that replace the defaults, or mask sets and names such as ``"secrets"`` that run before them.
            mining: Full mining configuration; the keyword arguments above override its fields.
            load_state: A state file of an earlier run to continue from: the templates it holds are the start of the
                tree, ``result()`` counts only the records of this miner, and the file must have been mined with the
                same masks and parameters.
            state_format: ``json`` (readable, the default) or ``binary`` (compact) for ``save_state``.
            examples: ``raw`` keeps example messages, ``masked`` applies the masking rules to them, ``none`` drops them.
            config: Settings from a ``logfold.toml`` (:func:`logfold.load_config`): they give the format, ``multiline``
                and the mining configuration wherever the call does not name them itself.

        Raises:
            ConfigError: If an option is invalid or the format is ``auto``.
            FormatError: If the format is invalid.
            EngineError: If the native extension is unavailable.
            StateError: If the state file is damaged, too large, newer than this logfold or mined with other settings.
        """
        chosen = format
        if chosen is None and config is not None and config.format != "auto":
            chosen = config.format
        if isinstance(chosen, str) and chosen == "auto":
            raise ConfigError(
                "a stream has no file to detect the format from",
                hint="name the format, for example format='plain'; 'logfold inspect FILE' finds it for a sample",
            )
        format, multiline, mining, _ = _apply_settings(
            config, "plain" if chosen is None else chosen, multiline, mining, None
        )
        resolved = resolve_format(format, (), multiline)
        self._spec = resolved.spec
        self._mining = _mining(
            mining, depth, sim_th, max_children, max_templates, masks, on_full=on_full, delimiters=delimiters
        )
        self._examples: ExamplesMode = examples
        self._state_format = state_format
        state = _state_request(load_state, None, state_format, self._mining, self._spec)
        self._live = LiveMiner(self._spec, self._mining, state)

    def add_many(self, records: Iterable[str]) -> int:
        """Mine a batch of complete records in one native call.

        Args:
            records: One string per record; a record may hold several lines. The format gives its level and time as for
                a file. A blank record is skipped and a record that the format cannot parse is counted as unparsed.

        Returns:
            The number of records that were mined.
        """
        return self._live.add_many(_items(records, "add_many"))

    def add_log_message(self, message: str) -> int:
        """Mine one record. It crosses the native boundary once per message; prefer :meth:`add_many`.

        Args:
            message: One record.

        Returns:
            1 when the record was mined, 0 when it was blank or the format could not parse it.
        """
        return self._live.add_many((message,))

    def add_lines(self, lines: Iterable[str]) -> int:
        """Mine physical lines, joining continuation lines to the record before them as a file would be read.

        A record of a multi-line format stays open until a line that starts the next record arrives or :meth:`flush` is
        called, so the last record of a batch is not mined yet. A line may end with a line feed.

        Args:
            lines: Physical lines in the order they were written.

        Returns:
            The number of records that this call completed and mined.
        """
        return self._live.add_lines(_items(lines, "add_lines"))

    def flush(self) -> int:
        """Mine the record that is still open, for example at the end of a stream.

        Returns:
            1 when a record was open, otherwise 0.
        """
        return self._live.flush()

    def match_many(self, records: Iterable[str], *, exact: bool = False) -> list[TemplateMatch | None]:
        """Assign a batch of complete records to the templates the miner holds, and learn nothing.

        The rule is the one of :func:`logfold.match` and ``logfold match``: the search of training first, then every
        template of the same length. The miner, its counters and a record that is still open (see :meth:`add_lines`) are
        not changed, and the answer for a record does not depend on the other records or on how they are split into
        calls. The batch is one native call.

        Args:
            records: One string per record; a record may hold several lines. The format gives the message as for a
                file.
            exact: A record fits a template only when every constant token of the template equals the token of the
                record (a wildcard accepts any token), as ``TemplateMiner.match`` of Drain3 does. By default the
                similarity of mining decides: at least the share ``sim_th`` of the tokens must equal the constant
                tokens, so a record that differs from a template in a word can still belong to it.

        Returns:
            One item per record: the :class:`~logfold.TemplateMatch` of its template, or ``None`` when the record fits
            no template, is blank or cannot be parsed by the format. The text is the one the template has now.
        """
        found, assigned = self._live.match_many(_items(records, "match_many"), exact)
        matches = [TemplateMatch(identifier, text) for identifier, text in found]
        return [None if index is None else matches[index] for index in assigned]

    def match(self, record: str, *, exact: bool = False) -> TemplateMatch | None:
        """Assign one record to a template without learning. It makes one native call; prefer :meth:`match_many`.

        Args:
            record: One record.
            exact: As in :meth:`match_many`.

        Returns:
            The :class:`~logfold.TemplateMatch`, or ``None`` as in :meth:`match_many`.
        """
        return self.match_many((record,), exact=exact)[0]

    def new_templates(self) -> list[str]:
        """Return the templates created since the previous call (or since the miner was opened).

        The text is the one the template had when it was created; later records may turn tokens into ``<*>``.
        Templates of a loaded state are not reported.

        Returns:
            Template texts in the order they were created.
        """
        return self._live.new_templates()

    def result(self) -> AnalysisResult:
        """Return the templates and counters of the records mined so far; the miner stays usable.

        A record that is still open (see :meth:`add_lines`) is not included until it is completed or flushed. The cost
        is proportional to the number of templates.

        Returns:
            The same result type as :func:`logfold.analyze`.
        """
        mined = self._live.result()
        summary = _summary(mined)
        templates = _templates(mined.templates, 0, summary.tz_aware, self._examples, Masker(self._mining.masks))
        return AnalysisResult(
            templates=templates,
            run=summary,
            metrics=mined.metrics,
            meta=_meta(self._spec, self._mining),
            warnings=tuple(_warnings(summary, self._mining.max_templates)),
        )

    def extract_parameters(self, template: str | Template, message: str) -> tuple[Parameter, ...] | None:
        """Give the values that a message has at the variable positions of a template, with the masks of this miner.

        See :func:`logfold.extract_parameters`.

        Args:
            template: The text of a template of this miner, or a ``Template`` of its result.
            message: One record.

        Returns:
            The parameters, or ``None`` when the message does not fit the template.
        """
        return extract_parameters(template, message, mining=self._mining)

    def save_state(self, path: PathLike, state_format: str | None = None) -> None:
        """Write the miner as a state file that ``analyze(load_state=...)``, ``match`` and ``Miner`` can read.

        Args:
            path: Where to write; a path that ends in ``.gz`` is compressed. The file holds templates and counts,
                never example lines.
            state_format: ``json`` or ``binary``; the one given to the constructor by default.

        Raises:
            ConfigError: If the format is unknown.
            StateError: If the file cannot be written.
        """
        chosen = self._state_format if state_format is None else state_format
        _state_request(None, None, chosen, self._mining, self._spec)
        self._live.save_state(os.fspath(path), chosen)


def _items(items: Iterable[str], method: str) -> Iterable[str]:
    """Refuse a single string, which would otherwise be mined one character at a time."""
    if isinstance(items, (str, bytes)):
        raise ConfigError(
            f"{method}() takes an iterable of strings, not one string",
            hint="pass a list, or call add_log_message() for a single record",
        )
    return items


def _summary(mined: MiningResult) -> RunSummary:
    info = mined.runs[0]
    return RunSummary(
        name=STREAM_NAME,
        files=info.files,
        lines=info.lines,
        records=info.records,
        unparsed=info.unparsed,
        bytes=info.bytes,
        tz_aware=info.tz_aware,
        overflowed=info.overflowed,
        evicted=info.evicted,
        out_of_range=info.out_of_range,
        untimed=info.untimed,
    )


def _warnings(summary: RunSummary, max_templates: int) -> list[str]:
    warnings = []
    if summary.lines and summary.unparsed_ratio > UNPARSED_WARNING_RATIO:
        warnings.append(
            f"{summary.unparsed_ratio:.0%} of lines did not match the format; check the format or enable multiline"
        )
    if summary.evicted:
        warnings.append(
            f"max_templates ({max_templates:,}) was reached; {summary.evicted:,} least recently used templates were "
            "dropped to make room, and their records are counted in catch-all templates"
        )
    elif summary.overflowed:
        warnings.append(
            f"max_templates ({max_templates:,}) was reached; extra records were pooled into catch-all templates"
        )
    return warnings
