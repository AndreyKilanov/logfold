"""Reporters: render an analysis or a diff as Markdown tables or as CSV.

A reporter has a ``name``, the ``kinds`` of results it supports and a ``render`` method that returns text. It sees only
the public result model (:class:`logfold.AnalysisResult`, :class:`logfold.DiffResult`), never the engine.
"""

from __future__ import annotations

import csv
import io

from logfold import AnalysisResult, DiffEntry, DiffResult

__all__ = ["CsvReporter", "MarkdownReporter"]


def _top(options: dict[str, object], default: int | None) -> int | None:
    value = options.get("top", default)
    return value if isinstance(value, int) and value > 0 else default


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


def _diff_sections(result: DiffResult) -> tuple[tuple[str, tuple[DiffEntry, ...]], ...]:
    return (
        ("new", result.new_templates),
        ("changed", result.changed),
        ("disappeared", result.disappeared),
    )


class MarkdownReporter:
    """Render an analysis or a diff as Markdown tables.

    Attributes:
        name: Name used in ``result.render("markdown")``.
        kinds: Result kinds the reporter supports.
    """

    name = "markdown"
    kinds = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: An analysis or a diff result.
            **options: ``top`` is the number of rows per table (default 20).

        Returns:
            The Markdown document.
        """
        top = _top(options, 20)
        if isinstance(result, DiffResult):
            return self._diff(result, top)
        return self._analysis(result, top)

    def _analysis(self, result: AnalysisResult, top: int | None) -> str:
        lines = [
            f"# {result.run.name}",
            "",
            f"{result.run.records:,} records, {len(result.templates):,} templates.",
            "",
            "| count | level | template |",
            "|---:|---|---|",
        ]
        lines.extend(f"| {t.count:,} | {t.level or ''} | `{_cell(t.text)}` |" for t in result.top(top or 20))
        return "\n".join(lines) + "\n"

    def _diff(self, result: DiffResult, top: int | None) -> str:
        lines = [
            f"# {result.before.name} -> {result.after.name}",
            "",
            f"{len(result.new_templates):,} new, {len(result.disappeared):,} disappeared, "
            f"{len(result.changed):,} changed, {result.unchanged:,} unchanged.",
        ]
        for title, entries in _diff_sections(result):
            lines.extend(["", f"## {title.capitalize()} templates", "", "| before | after | level | template |"])
            lines.append("|---:|---:|---|---|")
            lines.extend(
                f"| {e.before_count:,} | {e.after_count:,} | {e.level or ''} | `{_cell(e.text)}` |"
                for e in entries[:top]
            )
        return "\n".join(lines) + "\n"


class CsvReporter:
    """Render an analysis or a diff as CSV, one template per row, for spreadsheets and scripts.

    Attributes:
        name: Name used in ``result.render("csv")``.
        kinds: Result kinds the reporter supports.
    """

    name = "csv"
    kinds = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: An analysis or a diff result.
            **options: ``top`` limits the rows (all rows by default; per section for a diff).

        Returns:
            The CSV text with a header row.
        """
        top = _top(options, None)
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        if isinstance(result, DiffResult):
            writer.writerow(["kind", "before_count", "after_count", "level", "template"])
            for kind, entries in _diff_sections(result):
                for e in entries[:top]:
                    writer.writerow([kind, e.before_count, e.after_count, e.level or "", e.text])
        else:
            writer.writerow(["count", "level", "first_seen", "last_seen", "template"])
            for t in result.templates[:top]:
                first = t.first_seen.isoformat() if t.first_seen else ""
                last = t.last_seen.isoformat() if t.last_seen else ""
                writer.writerow([t.count, t.level or "", first, last, t.text])
        return buffer.getvalue()
