"""Plain-text reporter (no dependencies); the CLI uses Rich when it is installed.

Values that come from a log are passed through :func:`logfold.ext.printable`, so the text is safe to print on a
terminal.
"""

from __future__ import annotations

from collections.abc import Sequence

from logfold.ext.text import printable
from logfold.model import AnalysisResult, DiffEntry, DiffResult, Template

DEFAULT_TOP = 20
TEXT_WIDTH = 100


def _clip(text: str, width: int = TEXT_WIDTH) -> str:
    flat = " ".join(printable(text).split())
    return flat if len(flat) <= width else flat[: width - 1] + "…"


def _analysis_lines(result: AnalysisResult, top: int) -> list[str]:
    run = result.run
    lines = [
        f"{printable(run.name)}: {run.records:,} records, {len(result.templates):,} templates, "
        f"{run.unparsed:,} unparsed lines, format {result.meta.format}, "
        f"{result.metrics.engine} engine, {result.metrics.wall_total_s:.2f}s",
    ]
    lines.extend(f"warning: {printable(text)}" for text in result.warnings)
    lines.append("")
    shown: Sequence[Template] = result.top(top)
    lines.append(f"{'count':>10}  {'share':>7}  {'level':<5}  template")
    for template in shown:
        share = template.count / run.records if run.records else 0.0
        lines.append(f"{template.count:>10,}  {share:>7.2%}  {template.level or '':<5}  {_clip(template.text)}")
    if len(result.templates) > len(shown):
        lines.append(f"... {len(result.templates) - len(shown):,} more templates")
    return lines


def _entries(title: str, entries: Sequence[DiffEntry], top: int) -> list[str]:
    lines = ["", f"{title} ({len(entries):,})"]
    if not entries:
        return [*lines, "  none"]
    lines.append(f"{'before':>10}  {'after':>10}  {'change':>8}  {'level':<5}  template")
    for entry in entries[:top]:
        change = f"x{entry.ratio:.2f}" if entry.ratio is not None else ("new" if entry.before_count == 0 else "gone")
        lines.append(
            f"{entry.before_count:>10,}  {entry.after_count:>10,}  {change:>8}  {entry.level or '':<5}  "
            f"{_clip(entry.text)}"
        )
    if len(entries) > top:
        lines.append(f"... {len(entries) - top:,} more")
    return lines


def _diff_lines(result: DiffResult, top: int) -> list[str]:
    lines = [
        f"{printable(result.before.name)} -> {printable(result.after.name)}: "
        f"{result.before.records:,} -> {result.after.records:,} records, "
        f"{len(result.new_templates):,} new ({len(result.new_alerts):,} WARN+), "
        f"{len(result.disappeared):,} disappeared, {len(result.changed):,} changed, {result.unchanged:,} unchanged, "
        f"{result.metrics.engine} engine, {result.metrics.wall_total_s:.2f}s",
    ]
    lines.extend(f"warning: {printable(text)}" for text in result.warnings)
    lines.extend(_entries("New templates", result.new_templates, top))
    lines.extend(_entries("Changed templates", result.changed, top))
    lines.extend(_entries("Disappeared templates", result.disappeared, top))
    return lines


class TextReporter:
    """Renders results as plain text tables.

    Attributes:
        name: ``text``.
        kinds: Supports analysis and diff results.
    """

    name: str = "text"
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: Result to render.
            **options: ``top`` (rows per table, default 20).

        Returns:
            The text with a trailing newline.
        """
        raw_top = options.get("top", DEFAULT_TOP)
        top = raw_top if isinstance(raw_top, int) and raw_top > 0 else DEFAULT_TOP
        lines = _diff_lines(result, top) if isinstance(result, DiffResult) else _analysis_lines(result, top)
        return "\n".join(lines) + "\n"
