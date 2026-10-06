"""Plugins that ship with logfold, registered when this package is imported.

Formats: ``logfmt``, ``serilog-clef``. Reporters: ``markdown``, ``csv``. Diff matchers: ``jaccard``.

They use the same extension points as third-party plugins (:mod:`logfold.ext`); a plugin package that registers the same
name replaces the default. :mod:`logfold.plugins.catalog` lists and installs further plugins;
:func:`list_plugins` and :func:`plugin_info` show both together.
"""

from __future__ import annotations

from logfold.ext.registry import register_format, register_matcher, register_reporter
from logfold.plugins.formats import LOGFMT, SERILOG_CLEF
from logfold.plugins.listing import PluginInfo, closest, list_plugins, plugin_info, unknown_name_hint
from logfold.plugins.matchers import JaccardMatcher
from logfold.plugins.reporters import CsvReporter, MarkdownReporter
from logfold.plugins.templates import write_template

register_format(LOGFMT.name, LOGFMT)
register_format(SERILOG_CLEF.name, SERILOG_CLEF)
register_reporter(MarkdownReporter())
register_reporter(CsvReporter())
register_matcher(JaccardMatcher())

__all__ = [
    "LOGFMT",
    "SERILOG_CLEF",
    "CsvReporter",
    "JaccardMatcher",
    "MarkdownReporter",
    "PluginInfo",
    "closest",
    "list_plugins",
    "plugin_info",
    "unknown_name_hint",
    "write_template",
]
