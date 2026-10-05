"""Public facade: :func:`analyze`, :func:`diff` and :func:`load_analysis`.

The facade turns user options into frozen configuration, picks an engine, runs one mining call and converts the
engine's plain-data answer into the public result model.
"""

from __future__ import annotations

from logfold.api.analysis import analyze
from logfold.api.compare import diff
from logfold.api.saved import load_analysis

__all__ = ["analyze", "diff", "load_analysis"]
