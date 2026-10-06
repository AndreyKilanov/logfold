"""Reporters for CI systems: a GitHub job summary and a JUnit XML test report.

Both show templates, never example lines: a job summary and a test report are read by everyone who can open the
repository, while a template has its values replaced by placeholders.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Sequence

from logfold.model import AnalysisResult, DiffEntry, DiffResult, Template
from logfold.plugins.reporter_text import alert_noun, code_span, int_option, iso, run_names, xml_text

__all__ = ["GithubSummaryReporter", "JunitReporter"]

_ALERTS = ("WARN", "ERROR", "FATAL")
_SUMMARY_BYTES = 900_000
"""A step summary may hold 1 MiB; the rest is left for what other steps write to the same file."""
_NAME_WIDTH = 80
_TEXT_WIDTH = 300


def _alerts_first(entries: Sequence[DiffEntry]) -> list[DiffEntry]:
    """Put the WARN+ entries before the others without changing the order inside either group."""
    return [e for e in entries if e.level in _ALERTS] + [e for e in entries if e.level not in _ALERTS]


def _level(level: str | None) -> str:
    return f"**{level}** " if level else ""


def _entry_line(entry: DiffEntry, kind: str) -> str:
    if kind == "changed" and entry.ratio is not None:
        counts = f"x{entry.ratio:.2f} ({entry.before_count:,} -> {entry.after_count:,})"
    elif kind == "disappeared":
        counts = f"{entry.before_count:,} -> 0"
    else:
        counts = f"{entry.after_count:,}"
    return f"- {_level(entry.level)}{counts} {code_span(entry.text, _TEXT_WIDTH)}"


def _template_line(template: Template, records: int) -> str:
    share = f"{template.count / records:.2%}" if records else "-"
    return f"- {_level(template.level)}{template.count:,} ({share}) {code_span(template.text, _TEXT_WIDTH)}"


def _warnings(result: AnalysisResult | DiffResult) -> list[str]:
    return ["", *(f"> warning: {code_span(text, _TEXT_WIDTH)}" for text in result.warnings)] if result.warnings else []


class GithubSummaryReporter:
    """Render a result as Markdown for ``$GITHUB_STEP_SUMMARY``.

    The text starts with a verdict line and a table of counts, then lists the templates (WARN and above first). The
    changed and disappeared lists are collapsed. Several steps can write to the summary, so the document is kept below
    a byte budget and says when it had to list fewer templates.

    Attributes:
        name: ``github-summary``.
        kinds: Supports analysis and diff results.
    """

    name = "github-summary"
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: An analysis or a diff result.
            **options: ``top`` is the number of templates per list (default 20); ``max_bytes`` is the size the text must
                stay under (default 900000), reached by listing fewer templates; the headings and the counts are always
                kept, so a budget below their size is exceeded.

        Returns:
            The Markdown document with a trailing newline.
        """
        top = int_option(options, "top", 20, minimum=0)
        budget = int_option(options, "max_bytes", _SUMMARY_BYTES)
        rows = top
        while True:
            text = self._document(result, rows, cut=rows < top)
            if len(text.encode("utf-8")) <= budget or rows == 0:
                return text
            rows //= 2

    def _document(self, result: AnalysisResult | DiffResult, rows: int, *, cut: bool) -> str:
        lines = self._diff(result, rows) if isinstance(result, DiffResult) else self._analysis(result, rows)
        if cut:
            lines.extend(["", f"_Lists are shortened to {rows} templates to fit the size limit of a job summary._"])
        return "\n".join(lines) + "\n"

    def _analysis(self, result: AnalysisResult, rows: int) -> list[str]:
        run = result.run
        lines = [
            f"## logfold: {code_span(run.name, _NAME_WIDTH, tail=True)}",
            "",
            f"{run.records:,} records, {len(result.templates):,} templates, {run.unparsed:,} unparsed lines.",
        ]
        counts = result.levels
        if counts:
            levels = ", ".join(f"{name} {count:,}" for name, count in reversed(list(counts.items())))
            lines.extend(["", f"Levels: {levels}"])
        lines.extend(_warnings(result))
        shown = result.top(rows)
        lines.extend(["", f"### Most frequent templates ({len(shown):,} of {len(result.templates):,})", ""])
        lines.extend(_template_line(template, run.records) for template in shown)
        return lines

    def _diff(self, result: DiffResult, rows: int) -> list[str]:
        alerts = len(result.new_alerts)
        verdict = f"**{alert_noun(alerts)}.**" if alerts else "**No new WARN+ templates.**"
        lines = [
            f"## logfold: {run_names(result.before.name, result.after.name, _NAME_WIDTH)}",
            "",
            verdict,
            "",
            "| new | WARN+ | disappeared | changed | unchanged | records |",
            "|---:|---:|---:|---:|---:|---|",
            f"| {len(result.new_templates):,} | {alerts:,} | {len(result.disappeared):,} | {len(result.changed):,} "
            f"| {result.unchanged:,} | {result.before.records:,} -> {result.after.records:,} |",
        ]
        lines.extend(_warnings(result))
        shown = _alerts_first(result.new_templates)[:rows]
        lines.extend(["", f"### New templates ({len(shown):,} of {len(result.new_templates):,})", ""])
        lines.extend(_entry_line(entry, "new") for entry in shown)
        for title, kind, entries in (
            ("Changed", "changed", result.changed),
            ("Disappeared", "disappeared", result.disappeared),
        ):
            if not entries:
                continue
            lines.extend(["", f"<details><summary>{title} templates ({len(entries):,})</summary>", ""])
            lines.extend(_entry_line(entry, kind) for entry in entries[:rows])
            lines.extend(["", "</details>"])
        return lines


def _case(parent: ET.Element, entry: DiffEntry, run_records: int) -> ET.Element:
    level = entry.level or "none"
    case = ET.SubElement(
        parent,
        "testcase",
        classname=f"logfold.new.{level}",
        name=f"{xml_text(entry.text, 200)} [{entry.id[:8]}]",
        time="0",
    )
    if entry.level in _ALERTS:
        share = f"{entry.after_count / run_records:.2%}" if run_records else "-"
        failure = ET.SubElement(
            case,
            "failure",
            message=f"new {level} template, {entry.after_count:,} records",
            type=level,
        )
        failure.text = "\n".join(
            (
                f"template: {xml_text(entry.text, 500)}",
                f"records: {entry.after_count:,} ({share} of the run)",
                f"first seen: {iso(entry.first_seen)}",
                f"last seen: {iso(entry.last_seen)}",
            )
        )
    return case


class JunitReporter:
    """Render a diff as JUnit XML: each new template is a test case and a new WARN+ template fails it.

    A pipeline that already shows JUnit results (GitLab, Jenkins, GitHub test reporters) then shows a new alarming
    message as a failed test. New templates below WARN pass. A diff without a new WARN+ template holds one passing case,
    so the report is never empty.

    Attributes:
        name: ``junit``.
        kinds: Supports diff results only.
    """

    name = "junit"
    kinds: tuple[str, ...] = ("diff",)

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: A diff result.
            **options: ``top`` is the number of passing cases for new templates below WARN (default 100); every new
                WARN+ template is always listed.

        Returns:
            The XML document with a trailing newline.

        Raises:
            TypeError: If ``result`` is not a diff result (the registry refuses this before the call).
        """
        if not isinstance(result, DiffResult):
            raise TypeError("the junit reporter renders diff results")
        top = int_option(options, "top", 100, minimum=0)
        alerts = [e for e in result.new_templates if e.level in _ALERTS]
        quiet = [e for e in result.new_templates if e.level not in _ALERTS][:top]
        root = ET.Element("testsuites")
        suite = ET.SubElement(
            root,
            "testsuite",
            name="logfold",
            tests=str(len(alerts) + len(quiet) or 1),
            failures=str(len(alerts)),
            errors="0",
            skipped="0",
            time="0",
        )
        properties = ET.SubElement(suite, "properties")
        for key, value in (
            ("before", xml_text(result.before.name, 200, tail=True)),
            ("after", xml_text(result.after.name, 200, tail=True)),
            ("new_templates", str(len(result.new_templates))),
            ("disappeared_templates", str(len(result.disappeared))),
            ("changed_templates", str(len(result.changed))),
            ("unchanged_templates", str(result.unchanged)),
        ):
            ET.SubElement(properties, "property", name=key, value=value)
        for entry in (*alerts, *quiet):
            _case(suite, entry, result.after.records)
        if not alerts and not quiet:
            ET.SubElement(suite, "testcase", classname="logfold.new", name="no new templates", time="0")
        ET.indent(root)
        return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
