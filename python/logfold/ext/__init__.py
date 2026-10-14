"""Extension points of logfold (stable, documented separately from the main API)."""

from __future__ import annotations

from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.log4j import log4j_format
from logfold.ext.mask_selection import ALL_SETS, MaskSelection, resolve_masks
from logfold.ext.mask_sets import MaskSet, load_mask_set, mask_fingerprint
from logfold.ext.masks import DEFAULT_MASKS, MaskRule
from logfold.ext.matchers import DiffMatcher
from logfold.ext.plugin_folders import default_plugin_dir, plugin_directories
from logfold.ext.registry import (
    add_plugin_directory,
    format_names,
    get_format,
    get_mask_set,
    get_matcher,
    get_reporter,
    get_source,
    mask_set_names,
    matcher_names,
    plugin_sources,
    register_format,
    register_mask_set,
    register_matcher,
    register_reporter,
    register_source,
    reporter_for_suffix,
    reporter_names,
    source_names,
)
from logfold.ext.reporters import Reporter
from logfold.ext.sources import Command, Source, SourceOptions
from logfold.ext.text import printable

__all__ = [
    "ALL_SETS",
    "DEFAULT_MASKS",
    "Command",
    "DiffMatcher",
    "Format",
    "FormatSpec",
    "JsonFormat",
    "MaskRule",
    "MaskSelection",
    "MaskSet",
    "PlainFormat",
    "RegexFormat",
    "Reporter",
    "Source",
    "SourceOptions",
    "add_plugin_directory",
    "default_plugin_dir",
    "format_names",
    "get_format",
    "get_mask_set",
    "get_matcher",
    "get_reporter",
    "get_source",
    "load_mask_set",
    "log4j_format",
    "mask_fingerprint",
    "mask_set_names",
    "matcher_names",
    "plugin_directories",
    "plugin_sources",
    "printable",
    "register_format",
    "register_mask_set",
    "register_matcher",
    "register_reporter",
    "register_source",
    "reporter_for_suffix",
    "reporter_names",
    "resolve_masks",
    "source_names",
]
