"""logfold: fold large logs into templates and compare two runs.

Public API::

    from logfold import analyze, diff

    result = analyze("app.log")
    result.top(10)
    comparison = diff("before.log", "after.log")
    comparison.new_templates
"""

from __future__ import annotations

from logfold import comparison as _comparison  # noqa: F401 - registers the built-in diff matchers
from logfold import formats as _formats  # noqa: F401 - registers the built-in formats
from logfold import reporters as _reporters  # noqa: F401 - registers the built-in reporters
from logfold._version import get_version
from logfold.api import analyze, diff
from logfold.config import DiffConfig, ExecutionConfig, MaskRule, MiningConfig
from logfold.errors import ConfigError, EngineError, FormatError, LogfoldError, SourceError
from logfold.model import AnalysisResult, DiffEntry, DiffResult, ResultMeta, RunMetrics, RunSummary, Template

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
    "LogfoldError",
    "MaskRule",
    "MiningConfig",
    "ResultMeta",
    "RunMetrics",
    "RunSummary",
    "SourceError",
    "Template",
    "__version__",
    "analyze",
    "diff",
]
