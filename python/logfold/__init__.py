"""logfold: fold large logs into templates and compare two runs.

Public API::

    from logfold import analyze, diff

    result = analyze("app.log")
    result.top(10)
    comparison = diff("before.log", "after.log")
    comparison.new_templates
    saved = load_analysis("result.json")
"""

from __future__ import annotations

from logfold import comparison as _comparison  # noqa: F401 - registers the built-in diff matchers
from logfold import formats as _formats  # noqa: F401 - registers the built-in formats
from logfold import plugins as _plugins  # noqa: F401 - registers the default plugins
from logfold import reporters as _reporters  # noqa: F401 - registers the built-in reporters
from logfold._version import get_version
from logfold.api import (
    Info,
    InspectedRecord,
    Inspection,
    analyze,
    diff,
    info,
    inspect_file,
    is_saved_analysis,
    load_analysis,
    match,
)
from logfold.config import DiffConfig, ExecutionConfig, MaskRule, MiningConfig
from logfold.errors import ConfigError, EngineError, FormatError, LogfoldError, SourceError, StateError
from logfold.model import (
    AnalysisResult,
    DiffEntry,
    DiffResult,
    ResultMeta,
    RunMetrics,
    RunSummary,
    Template,
    Unmatched,
)
from logfold.settings import Settings, load_config

__version__ = get_version()

__all__ = [
    "AnalysisResult",
    "ConfigError",
    "DiffConfig",
    "DiffEntry",
    "DiffResult",
    "EngineError",
    "ExecutionConfig",
    "FormatError",
    "Info",
    "InspectedRecord",
    "Inspection",
    "LogfoldError",
    "MaskRule",
    "MiningConfig",
    "ResultMeta",
    "RunMetrics",
    "RunSummary",
    "Settings",
    "SourceError",
    "StateError",
    "Template",
    "Unmatched",
    "__version__",
    "analyze",
    "diff",
    "info",
    "inspect_file",
    "is_saved_analysis",
    "load_analysis",
    "load_config",
    "match",
]
