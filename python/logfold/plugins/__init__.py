"""Plugins that ship with logfold, registered when this package is imported.

Formats: ``logfmt``, ``serilog-clef``, ``haproxy``, ``postgresql``, ``postgresql-csv``, ``log4j``, ``docker-json``,
``github-actions``. Reporters: ``markdown``, ``csv``, ``github-summary``, ``junit``, ``chat-message``,
``prometheus``. Diff matchers: ``jaccard``, ``jaccard-idf``, ``overlap``,
``rules``. Mask sets: ``default``, ``secrets``, ``credentials``, ``pii``, ``payment``. Sources: ``docker``, ``kubectl``,
``journalctl``.

They use the same extension points as third-party plugins (:mod:`logfold.ext`); a plugin package that registers the same
name replaces the default. :mod:`logfold.plugins.catalog` lists and installs further plugins;
:func:`list_plugins` and :func:`plugin_info` show both together.
"""

from __future__ import annotations

from logfold.ext.registry import (
    register_format,
    register_mask_set,
    register_matcher,
    register_reporter,
    register_source,
)
from logfold.plugins.formats import LOGFMT, SERILOG_CLEF
from logfold.plugins.formats_servers import DOCKER_JSON, GITHUB_ACTIONS, HAPROXY, LOG4J, POSTGRESQL, POSTGRESQL_CSV
from logfold.plugins.listing import PluginInfo, closest, list_plugins, plugin_info, unknown_name_hint
from logfold.plugins.masks import CREDENTIALS, PAYMENT, PII, SECRETS, builtin_mask_sets
from logfold.plugins.masks import DEFAULT as DEFAULT_MASK_SET
from logfold.plugins.matchers import JaccardIdfMatcher, JaccardMatcher, OverlapMatcher, RulesMatcher
from logfold.plugins.reporters import CsvReporter, MarkdownReporter
from logfold.plugins.reporters_ci import GithubSummaryReporter, JunitReporter
from logfold.plugins.reporters_feeds import ChatMessageReporter, PrometheusReporter
from logfold.plugins.scaffold import write_template
from logfold.plugins.sources import DockerSource, JournalctlSource, KubectlSource, builtin_sources

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
for _mask_set in builtin_mask_sets():
    register_mask_set(_mask_set)
for _source in builtin_sources():
    register_source(_source)

__all__ = [
    "CREDENTIALS",
    "DEFAULT_MASK_SET",
    "DOCKER_JSON",
    "GITHUB_ACTIONS",
    "HAPROXY",
    "LOG4J",
    "LOGFMT",
    "PAYMENT",
    "PII",
    "POSTGRESQL",
    "POSTGRESQL_CSV",
    "SECRETS",
    "SERILOG_CLEF",
    "ChatMessageReporter",
    "CsvReporter",
    "DockerSource",
    "GithubSummaryReporter",
    "JaccardIdfMatcher",
    "JaccardMatcher",
    "JournalctlSource",
    "JunitReporter",
    "KubectlSource",
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
