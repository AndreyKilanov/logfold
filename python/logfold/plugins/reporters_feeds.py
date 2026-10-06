"""Reporters that feed other systems: a chat message and Prometheus metrics. Nothing is sent anywhere.

Both show templates, never example lines (see :mod:`logfold.plugins.reporters_ci`).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from logfold.levels import LEVEL_NAMES
from logfold.model import AnalysisResult, DiffEntry, DiffResult, Template
from logfold.plugins.reporter_text import alert_noun, code_span, defuse_mentions, int_option, label_value, run_names

__all__ = ["ChatMessageReporter", "PrometheusReporter"]

_ALERTS = ("WARN", "ERROR", "FATAL")
_CHAT_CHARS = 3000
"""The longest text of one Slack section block; Telegram allows 4096 and Mattermost 16383."""
_NAME_WIDTH = 60
_TEXT_WIDTH = 200
_LABEL_WIDTH = 120
_MORE_RESERVE = 30
"""Room kept for the closing ``... and N more`` line."""


def _item(entry: Template | DiffEntry) -> str:
    count = entry.count if isinstance(entry, Template) else entry.after_count
    return (
        f"- {entry.level + ' ' if entry.level else ''}{count:,} x {code_span(defuse_mentions(entry.text), _TEXT_WIDTH)}"
    )


class ChatMessageReporter:
    """Render a result as a short message for Slack, Mattermost or Telegram.

    The message is plain text: a headline, a line of counts and a list with the new templates (WARN and above first)
    in code spans, and the mention syntax of Slack and Mattermost (``<!here>``, ``@channel``) is broken with a
    zero-width space, so a log line cannot ping a channel. The text is only returned; sending it is up to the pipeline.

    Attributes:
        name: ``chat-message``.
        kinds: Supports analysis and diff results.
    """

    name = "chat-message"
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: An analysis or a diff result.
            **options: ``top`` is the number of templates listed (default 5); ``max_chars`` is the length the message
                must stay within (default 3000), reached by listing fewer templates.

        Returns:
            The message with a trailing newline.
        """
        top = int_option(options, "top", 5, minimum=0)
        limit = int_option(options, "max_chars", _CHAT_CHARS)
        if isinstance(result, DiffResult):
            head, entries = self._diff(result)
        else:
            head, entries = self._analysis(result)
        lines = list(head)
        used = len("\n".join(lines))
        shown = 0
        for entry in entries[:top]:
            item = _item(entry)
            if used + len(item) + 1 + _MORE_RESERVE > limit:
                break
            lines.append(item)
            used += len(item) + 1
            shown += 1
        if shown < len(entries):
            lines.append(f"... and {len(entries) - shown:,} more")
        return "\n".join(lines) + "\n"

    def _analysis(self, result: AnalysisResult) -> tuple[list[str], Sequence[Template | DiffEntry]]:
        run = result.run
        head = [
            f"logfold: {code_span(defuse_mentions(run.name), _NAME_WIDTH, tail=True)}",
            f"{run.records:,} records, {len(result.templates):,} templates, {run.unparsed:,} unparsed lines.",
            "Most frequent templates:",
        ]
        return head, result.templates

    def _diff(self, result: DiffResult) -> tuple[list[str], Sequence[Template | DiffEntry]]:
        alerts = len(result.new_alerts)
        new = result.new_templates
        head = [
            f"logfold: {run_names(result.before.name, result.after.name, _NAME_WIDTH)}",
            f"{alert_noun(alerts)} of {len(new):,} new, {len(result.disappeared):,} disappeared, "
            f"{len(result.changed):,} changed.",
        ]
        if new:
            head.append("New templates:")
        ordered = [e for e in new if e.level in _ALERTS] + [e for e in new if e.level not in _ALERTS]
        return head, ordered


def _sample(name: str, labels: Sequence[tuple[str, str]], value: int) -> str:
    if not labels:
        return f"{name} {value}"
    pairs = ",".join(f'{key}="{text}"' for key, text in labels)
    return f"{name}{{{pairs}}} {value}"


def _family(name: str, help_text: str, samples: Iterable[str]) -> list[str]:
    body = list(samples)
    return [f"# HELP {name} {help_text}", f"# TYPE {name} gauge", *body] if body else []


def _template_labels(entry_id: str, level: str | None, text: str) -> list[tuple[str, str]]:
    labels = [("id", entry_id)]
    if level:
        labels.append(("level", level))
    labels.append(("template", label_value(text, _LABEL_WIDTH)))
    return labels


class PrometheusReporter:
    """Render a result as Prometheus gauges in the text exposition format.

    Write the file to the textfile directory of the node exporter (``--out logfold.prom``), which publishes it on the
    next scrape. The values describe one run, so they are gauges, and the file is replaced by every run, which removes
    the series of templates that no longer exist.

    The per-template series carry the template text in a label, so their number is bounded by ``top``.

    Attributes:
        name: ``prometheus``.
        kinds: Supports analysis and diff results.
    """

    name = "prometheus"
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: An analysis or a diff result.
            **options: ``top`` is the number of templates that get a series of their own, per section for a diff
                (default 50).

        Returns:
            The exposition text with a trailing newline.
        """
        top = int_option(options, "top", 50, minimum=0)
        lines = self._diff(result, top) if isinstance(result, DiffResult) else self._analysis(result, top)
        return "\n".join(lines) + "\n"

    def _analysis(self, result: AnalysisResult, top: int) -> list[str]:
        run = result.run
        levels = sorted(result.levels.items(), key=lambda item: LEVEL_NAMES.index(item[0]))
        lines = _family(
            "logfold_records", "Records parsed from the log.", [_sample("logfold_records", [], run.records)]
        )
        lines += _family(
            "logfold_unparsed_lines",
            "Lines that no record claimed.",
            [_sample("logfold_unparsed_lines", [], run.unparsed)],
        )
        lines += _family(
            "logfold_templates", "Distinct templates.", [_sample("logfold_templates", [], len(result.templates))]
        )
        lines += _family(
            "logfold_level_records",
            "Records per log level.",
            (_sample("logfold_level_records", [("level", name)], count) for name, count in levels),
        )
        lines += _family(
            "logfold_template_records",
            "Records of the most frequent templates.",
            (
                _sample("logfold_template_records", _template_labels(t.id, t.level, t.text), t.count)
                for t in result.top(top)
            ),
        )
        return lines

    def _diff(self, result: DiffResult, top: int) -> list[str]:
        counts = (
            ("new", len(result.new_templates)),
            ("disappeared", len(result.disappeared)),
            ("changed", len(result.changed)),
            ("unchanged", result.unchanged),
        )
        lines = _family(
            "logfold_diff_records",
            "Records of each run.",
            (
                _sample("logfold_diff_records", [("side", "before")], result.before.records),
                _sample("logfold_diff_records", [("side", "after")], result.after.records),
            ),
        )
        lines += _family(
            "logfold_diff_templates",
            "Templates by what changed between the runs.",
            (_sample("logfold_diff_templates", [("change", kind)], count) for kind, count in counts),
        )
        lines += _family(
            "logfold_diff_new_alerts",
            "New templates at WARN or above.",
            [_sample("logfold_diff_new_alerts", [], len(result.new_alerts))],
        )
        lines += _family(
            "logfold_diff_template_records",
            "Records of the listed templates in each run.",
            self._entries(result, top),
        )
        return lines

    def _entries(self, result: DiffResult, top: int) -> Iterable[str]:
        sections: tuple[tuple[str, tuple[DiffEntry, ...]], ...] = (
            ("new", result.new_templates),
            ("changed", result.changed),
            ("disappeared", result.disappeared),
        )
        for change, entries in sections:
            for entry in entries[:top]:
                base = [("change", change), *_template_labels(entry.id, entry.level, entry.text)]
                yield _sample("logfold_diff_template_records", [*base, ("side", "before")], entry.before_count)
                yield _sample("logfold_diff_template_records", [*base, ("side", "after")], entry.after_count)
