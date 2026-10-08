"""Resolve a diff matcher by name and describe the built-in ones for the native comparison.

A built-in matcher pairs templates in the extension by itself. The comparison of a whole result can also run in the
extension in one call; this module tells which matcher and which parameters that call takes. A subclass of a built-in
matcher and a plugin matcher always run their own Python code.
"""

from __future__ import annotations

from logfold.comparison import ExactMatcher, TokenSubsetMatcher
from logfold.errors import ConfigError
from logfold.ext import registry
from logfold.ext.matchers import DiffMatcher
from logfold.plugins.matchers import JaccardIdfMatcher, JaccardMatcher, OverlapMatcher, RulesMatcher

RULES_PREFIX = "rules:"

NativeSpec = tuple[str, "float | None", "tuple[tuple[str, str], ...] | None"]
"""A built-in matcher the extension implements: ``(kind, threshold, rules)``."""

_SCORING = (("jaccard", JaccardMatcher), ("jaccard_idf", JaccardIdfMatcher), ("overlap", OverlapMatcher))


def native_spec(matcher: DiffMatcher) -> NativeSpec | None:
    """Describe a built-in matcher the extension implements.

    Args:
        matcher: A registered matcher.

    Returns:
        ``(kind, threshold, rules)``, or ``None`` for a plugin or a subclass of a built-in matcher.
    """
    if type(matcher) is ExactMatcher:
        return ("exact", None, None)
    if type(matcher) is TokenSubsetMatcher:
        return ("token_subset", None, None)
    for kind, scoring in _SCORING:
        if type(matcher) is scoring:
            return (kind, float(matcher.threshold), None)
    if type(matcher) is RulesMatcher:
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
