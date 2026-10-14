"""Extension points of logfold (stable, documented separately from the main API)."""

from __future__ import annotations

from logfold.ext.formats import Format, FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.ext.log4j import log4j_format
from logfold.ext.mask_selection import MaskSelection, resolve_masks
from logfold.ext.mask_sets import MaskSet, load_mask_set, mask_fingerprint
from logfold.ext.masks import DEFAULT_MASKS, MaskRule
from logfold.ext.matchers import DiffMatcher
from logfold.ext.registry import (
    add_plugin_directory,
    default_plugin_dir,
    format_names,
    get_format,
    get_mask_set,
    get_matcher,
    get_reporter,
    mask_set_names,
    matcher_names,
    plugin_directories,
    plugin_sources,
    register_format,
    register_mask_set,
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
    "MaskSelection",
    "MaskSet",
    "PlainFormat",
    "RegexFormat",
    "Reporter",
    "add_plugin_directory",
    "default_plugin_dir",
    "format_names",
    "get_format",
    "get_mask_set",
    "get_matcher",
    "get_reporter",
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
    "reporter_for_suffix",
    "reporter_names",
    "resolve_masks",
]
