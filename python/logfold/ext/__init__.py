"""Extension points of logfold (stable, documented separately from the main API)."""

from __future__ import annotations

from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.log4j import log4j_format
from logfold.ext.masks import DEFAULT_MASKS, MaskRule
from logfold.ext.matchers import DiffMatcher
from logfold.ext.registry import (
    add_plugin_directory,
    default_plugin_dir,
    format_names,
    get_format,
    get_matcher,
    get_reporter,
    matcher_names,
    plugin_directories,
    plugin_sources,
    register_format,
    register_matcher,
    register_reporter,
    reporter_for_suffix,
    reporter_names,
)
from logfold.ext.reporters import Reporter
from logfold.ext.text import printable

__all__ = [
    "DEFAULT_MASKS",
    "DiffMatcher",
    "Format",
    "FormatSpec",
    "JsonFormat",
    "MaskRule",
    "PlainFormat",
    "RegexFormat",
    "Reporter",
    "add_plugin_directory",
    "default_plugin_dir",
    "format_names",
    "get_format",
    "get_matcher",
    "get_reporter",
    "log4j_format",
    "matcher_names",
    "plugin_directories",
    "plugin_sources",
    "printable",
    "register_format",
    "register_matcher",
    "register_reporter",
    "reporter_for_suffix",
    "reporter_names",
]
