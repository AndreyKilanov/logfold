"""Use the native implementation of the built-in diff matchers when it is available.

The pure-Python matchers are the reference. When the Rust extension provides the same matcher, the call is delegated to
it; the result is identical (see the differential tests), only faster. A subclass of a built-in matcher and a plugin
matcher always run their own Python code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from logfold.comparison import TokenSubsetMatcher
from logfold.engines import native
from logfold.ext.matchers import DiffMatcher
from logfold.plugins.matchers import JaccardMatcher


class _NativeMatcher:
    """Runs a built-in matcher in the extension and falls back to the Python code for text it cannot pass."""

    def __init__(self, base: DiffMatcher, kind: str, threshold: float | None) -> None:
        self.name = base.name
        self._base = base
        self._kind = kind
        self._threshold = threshold

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates like the wrapped matcher does.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Index pairs, identical to those of the wrapped Python matcher.
        """
        try:
            return native.match_templates(self._kind, before_only, after_only, self._threshold)
        except (UnicodeError, ValueError):
            return self._base.match(before_only, after_only)


def accelerated(matcher: DiffMatcher, enabled: bool = True) -> DiffMatcher:
    """Return the native version of a built-in matcher, or ``matcher`` itself.

    Args:
        matcher: A registered matcher.
        enabled: ``False`` keeps the Python implementation (the pure-Python engine was requested).

    Returns:
        A matcher with the same name and the same results. A ``jaccard`` threshold that is not a positive number keeps
        the Python implementation, which scores every pair or rejects the value.
    """
    if not enabled or not native.supports_matching():
        return matcher
    if type(matcher) is TokenSubsetMatcher:
        return _NativeMatcher(matcher, "token_subset", None)
    if type(matcher) is JaccardMatcher and math.isfinite(matcher.threshold) and matcher.threshold > 0:
        return _NativeMatcher(matcher, "jaccard", float(matcher.threshold))
    return matcher
