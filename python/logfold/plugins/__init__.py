"""Plugins that ship with logfold, registered when this package is imported.

Formats: ``logfmt``, ``serilog-clef``, ``haproxy``, ``postgresql``, ``postgresql-csv``, ``log4j``, ``docker-json``,
``github-actions``. Reporters: ``markdown``, ``csv``. Diff matchers: ``jaccard``, ``jaccard-idf``, ``overlap``,
``rules``.

They use the same extension points as third-party plugins (:mod:`logfold.ext`); a plugin package that registers the same
name replaces the default. :mod:`logfold.plugins.catalog` lists and installs further plugins;
:func:`list_plugins` and :func:`plugin_info` show both together.
"""

from __future__ import annotations

from logfold.ext.registry import register_format, register_matcher, register_reporter
from logfold.plugins.formats import LOGFMT, SERILOG_CLEF
from logfold.plugins.formats_infra import DOCKER_JSON, GITHUB_ACTIONS, HAPROXY, LOG4J, POSTGRESQL, POSTGRESQL_CSV
from logfold.plugins.listing import PluginInfo, closest, list_plugins, plugin_info, unknown_name_hint
from logfold.plugins.matchers import JaccardIdfMatcher, JaccardMatcher, OverlapMatcher, RulesMatcher
from logfold.plugins.reporters import CsvReporter, MarkdownReporter
from logfold.plugins.templates import write_template

register_format(LOGFMT.name, LOGFMT)
register_format(SERILOG_CLEF.name, SERILOG_CLEF)
for _format in (HAPROXY, POSTGRESQL, POSTGRESQL_CSV, LOG4J, DOCKER_JSON, GITHUB_ACTIONS):
    register_format(_format.name, _format)
register_reporter(MarkdownReporter())
register_reporter(CsvReporter())
register_matcher(JaccardMatcher())
register_matcher(JaccardIdfMatcher())
register_matcher(OverlapMatcher())
register_matcher(RulesMatcher())

__all__ = [
    "DOCKER_JSON",
    "GITHUB_ACTIONS",
    "HAPROXY",
    "LOG4J",
    "LOGFMT",
    "POSTGRESQL",
    "POSTGRESQL_CSV",
    "SERILOG_CLEF",
    "CsvReporter",
    "JaccardIdfMatcher",
    "JaccardMatcher",
    "MarkdownReporter",
    "OverlapMatcher",
    "PluginInfo",
    "RulesMatcher",
    "closest",
    "list_plugins",
    "plugin_info",
    "unknown_name_hint",
    "write_template",
]
