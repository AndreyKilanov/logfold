"""Example logfold plugins: three log formats, two reporters and two diff matchers.

Every object is registered through an entry point in ``pyproject.toml``; logfold finds them as soon as the package is
installed. See ``docs/plugins.md`` in the logfold repository for how to use and write plugins.
"""

from __future__ import annotations

from logfold_example_plugin.formats import CI_BLOCKS, LOGFMT, SERILOG_CLEF
from logfold_example_plugin.matchers import FirstWordMatcher, JaccardMatcher
from logfold_example_plugin.reporters import CsvReporter, MarkdownReporter

__all__ = [
    "CI_BLOCKS",
    "LOGFMT",
    "SERILOG_CLEF",
    "CsvReporter",
    "FirstWordMatcher",
    "JaccardMatcher",
    "MarkdownReporter",
]
