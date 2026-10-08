"""Plugins that ship with logfold, registered when this package is imported.

Formats: ``logfmt``, ``serilog-clef``, ``haproxy``, ``postgresql``, ``postgresql-csv``, ``log4j``, ``docker-json``,
``github-actions``. Reporters: ``markdown``, ``csv``, ``github-summary``, ``junit``, ``chat-message``,
``prometheus``. Diff matchers: ``jaccard``, ``jaccard-idf``, ``overlap``,
``rules``.

They use the same extension points as third-party plugins (:mod:`logfold.ext`); a plugin package that registers the same
name replaces the default. :mod:`logfold.plugins.catalog` lists and installs further plugins;
:func:`list_plugins` and :func:`plugin_info` show both together.
"""

from __future__ import annotations

from logfold.ext.registry import register_format, register_matcher, register_reporter
from logfold.plugins.formats import LOGFMT, SERILOG_CLEF
from logfold.plugins.formats_servers import DOCKER_JSON, GITHUB_ACTIONS, HAPROXY, LOG4J, POSTGRESQL, POSTGRESQL_CSV
from logfold.plugins.listing import PluginInfo, closest, list_plugins, plugin_info, unknown_name_hint
from logfold.plugins.matchers import JaccardIdfMatcher, JaccardMatcher, OverlapMatcher, RulesMatcher
from logfold.plugins.reporters import CsvReporter, MarkdownReporter
from logfold.plugins.reporters_ci import GithubSummaryReporter, JunitReporter
from logfold.plugins.reporters_feeds import ChatMessageReporter, PrometheusReporter
from logfold.plugins.scaffold import write_template

register_format(LOGFMT.name, LOGFMT)
register_format(SERILOG_CLEF.name, SERILOG_CLEF)
for _format in (HAPROXY, POSTGRESQL, POSTGRESQL_CSV, LOG4J, DOCKER_JSON, GITHUB_ACTIONS):
    register_format(_format.name, _format)
register_reporter(MarkdownReporter())
register_reporter(CsvReporter())
for _reporter in (GithubSummaryReporter(), JunitReporter(), ChatMessageReporter(), PrometheusReporter()):
    register_reporter(_reporter)
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
    "ChatMessageReporter",
    "CsvReporter",
    "GithubSummaryReporter",
    "JaccardIdfMatcher",
    "JaccardMatcher",
    "JunitReporter",
    "MarkdownReporter",
    "OverlapMatcher",
    "PluginInfo",
    "PrometheusReporter",
    "RulesMatcher",
    "closest",
    "list_plugins",
    "plugin_info",
    "unknown_name_hint",
    "write_template",
]
