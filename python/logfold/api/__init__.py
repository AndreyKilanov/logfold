"""Public facade: analyze, match, check, Miner, extract_parameters, diff, load_analysis, inspect_file and info.

The facade turns user options into frozen configuration, picks an engine, runs one mining call and converts the
engine's plain-data answer into the public result model.
"""

from __future__ import annotations

from logfold.api.analyze import analyze
from logfold.api.check import check
from logfold.api.diff import diff
from logfold.api.info import Info, info
from logfold.api.inspecting import InspectedRecord, Inspection, inspect_file
from logfold.api.match import match
from logfold.api.miner import Miner
from logfold.api.parameters import extract_parameters
from logfold.api.saved import is_saved_analysis, load_analysis

__all__ = [
    "Info",
    "InspectedRecord",
    "Inspection",
    "Miner",
    "analyze",
    "check",
    "diff",
    "extract_parameters",
    "info",
    "inspect_file",
    "is_saved_analysis",
    "load_analysis",
    "match",
]
