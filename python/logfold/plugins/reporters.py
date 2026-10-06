"""Reporters that ship with logfold as default plugins: Markdown tables and CSV.

Log lines are untrusted input, so every value that comes from a log is neutralized for the target format: Markdown
table cells cannot break out of their cell or code span, and CSV cells that a spreadsheet would read as a formula get
a leading apostrophe.
"""

from __future__ import annotations

import csv
import io

from logfold.ext.text import printable
from logfold.model import AnalysisResult, DiffEntry, DiffResult

__all__ = ["CsvReporter", "MarkdownReporter"]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _top(options: dict[str, object], default: int | None) -> int | None:
    value = options.get("top", default)
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else default


def _md(text: str) -> str:
    return printable(text).replace("|", "/").replace("`", "'").replace("\n", " ")


def _csv(text: str) -> str:
    return "'" + text if text.startswith(_FORMULA_PREFIXES) else text


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
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: An analysis or a diff result.
            **options: ``top`` is the number of rows per table (default 20).

        Returns:
            The Markdown document.
        """
        top = _top(options, 20) or 20
        if isinstance(result, DiffResult):
            return self._diff(result, top)
        return self._analysis(result, top)

    def _analysis(self, result: AnalysisResult, top: int) -> str:
        lines = [
            f"# {_md(result.run.name)}",
            "",
            f"{result.run.records:,} records, {len(result.templates):,} templates.",
            "",
            "| count | level | template |",
            "|---:|---|---|",
        ]
        lines.extend(f"| {t.count:,} | {t.level or ''} | `{_md(t.text)}` |" for t in result.top(top))
        return "\n".join(lines) + "\n"

    def _diff(self, result: DiffResult, top: int) -> str:
        lines = [
            f"# {_md(result.before.name)} -> {_md(result.after.name)}",
            "",
            f"{len(result.new_templates):,} new, {len(result.disappeared):,} disappeared, "
            f"{len(result.changed):,} changed, {result.unchanged:,} unchanged.",
        ]
        for title, entries in _diff_sections(result):
            lines.extend(["", f"## {title.capitalize()} templates", "", "| before | after | level | template |"])
            lines.append("|---:|---:|---|---|")
            lines.extend(
                f"| {e.before_count:,} | {e.after_count:,} | {e.level or ''} | `{_md(e.text)}` |" for e in entries[:top]
            )
        return "\n".join(lines) + "\n"


class CsvReporter:
    """Render an analysis or a diff as CSV, one template per row, for spreadsheets and scripts.

    Attributes:
        name: Name used in ``result.render("csv")``.
        kinds: Result kinds the reporter supports.
    """

    name = "csv"
    kinds: tuple[str, ...] = ("analysis", "diff")

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
                    writer.writerow([kind, e.before_count, e.after_count, e.level or "", _csv(e.text)])
        else:
            writer.writerow(["count", "level", "first_seen", "last_seen", "template"])
            for t in result.templates[:top]:
                first = t.first_seen.isoformat() if t.first_seen else ""
                last = t.last_seen.isoformat() if t.last_seen else ""
                writer.writerow([t.count, t.level or "", first, last, _csv(t.text)])
        return buffer.getvalue()
