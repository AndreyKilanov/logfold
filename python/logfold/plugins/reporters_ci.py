"""Reporters for CI systems: a GitHub job summary and a JUnit XML test report.

Both show templates, never example lines: a job summary and a test report are read by everyone who can open the
repository, while a template has its values replaced by placeholders.

The native engine writes the text; the contract is ``docs/ALGORITHM.md`` section 12.
"""

from __future__ import annotations

from logfold.model import AnalysisResult, DiffResult
from logfold.plugins.report_data import int_option, render_native

__all__ = ["GithubSummaryReporter", "JunitReporter"]

_SUMMARY_BYTES = 900_000
"""A step summary may hold 1 MiB; the rest is left for what other steps write to the same file."""


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
        levels = list(result.levels.items()) if isinstance(result, AnalysisResult) else []
        return render_native(
            self.name, result, {"top": top, "max_bytes": budget}, ("levels", "before", "ratios"), levels
        )


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
        return render_native(self.name, result, {"top": top}, ("ids", "levels", "moments"))
