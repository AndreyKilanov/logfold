"""Example logfold plugin: a log format, a Markdown reporter and a diff matcher.

The three objects are registered through entry points in ``pyproject.toml``; logfold finds them as soon as the package
is installed.
"""

from __future__ import annotations

from collections.abc import Sequence

from logfold import AnalysisResult, DiffResult
from logfold.ext import RegexFormat

__all__ = ["EXAMPLE", "FirstWordMatcher", "MarkdownReporter"]

EXAMPLE = RegexFormat(
    name="example",
    pattern=r"^(?P<ts>\d{2}/\w{3}/\d{4}:[\d:.]+) (?P<lvl>\w+) (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    ts_format="%d/%b/%Y:%H:%M:%S.%f",
)
"""A line such as ``04/Oct/2026:10:00:01.123 WARN slow query took 412 ms``.

A format is data, not code: the engine compiles it into a fast parser, so it costs nothing per line.
"""


def _cell(text: str) -> str:
    return text.replace("|", "/").replace("\n", " ")


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
        raw = options.get("top", 20)
        top = raw if isinstance(raw, int) else 20
        if isinstance(result, DiffResult):
            return self._diff(result, top)
        return self._analysis(result, top)

    def _analysis(self, result: AnalysisResult, top: int) -> str:
        lines = [
            f"# {result.run.name}",
            "",
            f"{result.run.records:,} records, {len(result.templates):,} templates.",
            "",
            "| count | level | template |",
            "|---:|---|---|",
        ]
        lines.extend(f"| {t.count:,} | {t.level or ''} | `{_cell(t.text)}` |" for t in result.top(top))
        return "\n".join(lines) + "\n"

    def _diff(self, result: DiffResult, top: int) -> str:
        lines = [
            f"# {result.before.name} -> {result.after.name}",
            "",
            f"{len(result.new_templates):,} new, {len(result.disappeared):,} disappeared, "
            f"{len(result.changed):,} changed, {result.unchanged:,} unchanged.",
        ]
        for title, entries in (
            ("New templates", result.new_templates),
            ("Changed templates", result.changed),
            ("Disappeared templates", result.disappeared),
        ):
            lines.extend(["", f"## {title}", "", "| before | after | level | template |", "|---:|---:|---|---|"])
            lines.extend(
                f"| {e.before_count:,} | {e.after_count:,} | {e.level or ''} | `{_cell(e.text)}` |"
                for e in entries[:top]
            )
        return "\n".join(lines) + "\n"


class FirstWordMatcher:
    """Treat templates that start with the same word as the same template.

    The miner already matches identical templates of the two runs. A matcher only sees the rest, the templates present
    in one run, and may pair them so that a reworded message is reported as ``changed`` instead of as one ``new`` and
    one ``disappeared`` template.

    Attributes:
        name: Name used by ``--matcher`` and :class:`logfold.DiffConfig`.
    """

    name = "first_word"

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates by their first word.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` in which every index occurs at most once.
        """
        pairs: list[tuple[int, int]] = []
        used: set[int] = set()
        for j, text in enumerate(after_only):
            for i, other in enumerate(before_only):
                if i not in used and other.split()[:1] == text.split()[:1]:
                    pairs.append((i, j))
                    used.add(i)
                    break
        return pairs
