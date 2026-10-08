"""Use the native implementation of the built-in diff matchers when it is available.

The pure-Python matchers are the reference. When the Rust extension provides the same matcher, the call is delegated to
it; the result is identical (see the differential tests), only faster. A subclass of a built-in matcher and a plugin
matcher always run their own Python code.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from logfold import _bridge
from logfold.comparison import ExactMatcher, TokenSubsetMatcher
from logfold.errors import ConfigError
from logfold.ext import registry
from logfold.ext.matchers import DiffMatcher
from logfold.plugins.matchers import JaccardIdfMatcher, JaccardMatcher, OverlapMatcher, RulesMatcher

RULES_PREFIX = "rules:"

NativeSpec = tuple[str, "float | None", "tuple[tuple[str, str], ...] | None"]
"""A built-in matcher the extension implements: ``(kind, threshold, rules)``."""

_SCORING = (("jaccard", JaccardMatcher), ("jaccard_idf", JaccardIdfMatcher), ("overlap", OverlapMatcher))


class _NativeMatcher:
    """Runs a built-in matcher in the extension and falls back to the Python code for text it cannot pass."""

    def __init__(self, base: DiffMatcher, spec: NativeSpec) -> None:
        self.name = base.name
        self._base = base
        self._kind, self._threshold, self._rules = spec

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates like the wrapped matcher does.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Index pairs, identical to those of the wrapped Python matcher.
        """
        try:
            return _bridge.match_templates(self._kind, before_only, after_only, self._threshold, self._rules)
        except (UnicodeError, ValueError):
            return self._base.match(before_only, after_only)


def native_spec(matcher: DiffMatcher) -> NativeSpec | None:
    """Describe a built-in matcher the extension implements.

    Args:
        matcher: A registered matcher.

    Returns:
        ``(kind, threshold, rules)``, or ``None`` for a plugin, a subclass of a built-in matcher, a ``rules`` matcher
        without rules, or a threshold that is not a positive number (the Python implementation scores every pair or
        finds no pair for those).
    """
    if type(matcher) is ExactMatcher:
        return ("exact", None, None)
    if type(matcher) is TokenSubsetMatcher:
        return ("token_subset", None, None)
    for kind, scoring in _SCORING:
        if type(matcher) is scoring:
            threshold = float(matcher.threshold)
            return (kind, threshold, None) if math.isfinite(threshold) and threshold > 0 else None
    if type(matcher) is RulesMatcher and matcher.rules:
        return ("rules", None, matcher.rules)
    return None


def resolve_matcher(name: str) -> DiffMatcher:
    """Return the matcher a user asked for by name; ``rules:FILE`` reads the rules of a file.

    Args:
        name: A registered matcher name, or ``rules:FILE``.

    Returns:
        The matcher.

    Raises:
        ConfigError: If the name is unknown, ``rules`` has no file, or the file cannot be read.
    """
    if name.startswith(RULES_PREFIX):
        return RulesMatcher.from_file(name[len(RULES_PREFIX) :])
    if name == RulesMatcher.name:
        raise ConfigError(
            "the rules matcher needs a file of rules",
            hint="use --matcher rules:FILE, with one 'TEMPLATE <=> TEMPLATE' per line",
        )
    return registry.get_matcher(name)


def accelerated(matcher: DiffMatcher, enabled: bool = True) -> DiffMatcher:
    """Return the native version of a built-in matcher, or ``matcher`` itself.

    Args:
        matcher: A registered matcher.
        enabled: ``False`` keeps the Python implementation (the pure-Python engine was requested).

    Returns:
        A matcher with the same name and the same results. A threshold that is not a positive number keeps the Python
        implementation: zero or less scores every pair, ``nan`` and infinity are reached by no pair.
    """
    if not enabled or not _bridge.supports_matching():
        return matcher
    spec = native_spec(matcher)
    if spec is None or spec[0] == "exact":
        return matcher
    return _NativeMatcher(matcher, spec)
