"""Reporters that feed other systems: a chat message and Prometheus metrics. Nothing is sent anywhere.

Both show templates, never example lines (see :mod:`logfold.plugins.reporters_ci`). The native engine writes the text;
the contract is ``docs/ALGORITHM.md`` section 12.
"""

from __future__ import annotations

from logfold.levels import severity
from logfold.model import AnalysisResult, DiffResult
from logfold.plugins.report_data import int_option, render_native

__all__ = ["ChatMessageReporter", "PrometheusReporter"]

_CHAT_CHARS = 3000
"""The longest text of one Slack section block; Telegram allows 4096 and Mattermost 16383."""


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
        return render_native(self.name, result, {"top": top, "max_chars": limit}, ("levels",))


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
        levels = (
            sorted(result.levels.items(), key=lambda item: severity(item[0]))
            if isinstance(result, AnalysisResult)
            else []
        )
        return render_native(self.name, result, {"top": top}, ("ids", "levels", "before"), levels)
