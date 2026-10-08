"""Built-in reporters: JSON, HTML and plain text."""

from __future__ import annotations

from logfold.ext.registry import register_reporter
from logfold.reporters.html import HtmlReporter
from logfold.reporters.json import JsonReporter
from logfold.reporters.text import TextReporter

register_reporter(JsonReporter())
register_reporter(HtmlReporter())
register_reporter(TextReporter())

__all__ = ["HtmlReporter", "JsonReporter", "TextReporter"]
