"""JSON reporter."""

from __future__ import annotations

import json
import re

from logfold.model import AnalysisResult, DiffResult
from logfold.reporters.payload import analysis_payload, diff_payload

_C1_AND_DEL = re.compile("[\x7f-\x9f]")
"""``json`` escapes the C0 controls but leaves DEL and the C1 codes (8-bit terminal escapes) raw; escape them too."""


class JsonReporter:
    """Renders results as JSON (schema version 1, see :mod:`logfold.reporters.payload`).

    Attributes:
        name: ``json``.
        kinds: Supports analysis and diff results.
    """

    name: str = "json"
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: Result to render.
            **options: ``indent`` (default 2) and ``limit`` (maximum templates per list, default all).

        Returns:
            The JSON document with a trailing newline.
        """
        indent = options.get("indent", 2)
        limit = options.get("limit")
        limit_value = int(limit) if isinstance(limit, int) else None
        indent_value = int(indent) if isinstance(indent, int) else None
        if isinstance(result, DiffResult):
            payload = diff_payload(result, limit_value)
        else:
            payload = analysis_payload(result, limit_value)
        text = json.dumps(payload, indent=indent_value, ensure_ascii=False)
        return _C1_AND_DEL.sub(lambda found: f"\\u{ord(found.group()):04x}", text) + "\n"
