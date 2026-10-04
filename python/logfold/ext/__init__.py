"""Extension points of logfold (stable, documented separately from the main API)."""

from __future__ import annotations

from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.masks import DEFAULT_MASKS, MaskRule
from logfold.ext.matchers import DiffMatcher
from logfold.ext.registry import (
    format_names,
    get_format,
    get_matcher,
    get_reporter,
    plugin_sources,
    register_format,
    register_matcher,
    register_reporter,
    reporter_names,
)
from logfold.ext.reporters import Reporter

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
    "format_names",
    "get_format",
    "get_matcher",
    "get_reporter",
    "plugin_sources",
    "register_format",
    "register_matcher",
    "register_reporter",
    "reporter_names",
]
