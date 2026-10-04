"""Masking rules: the part of a message that varies is replaced by a stable token before mining."""

from __future__ import annotations

import re
from collections.abc import Sequence

from logfold.config import DEFAULT_MASKS, MaskRule
from logfold.errors import ConfigError

__all__ = ["DEFAULT_MASKS", "MaskRule", "Masker", "validate_masks"]


def validate_masks(masks: Sequence[MaskRule]) -> None:
    """Check that every rule compiles and cannot match the empty string.

    Args:
        masks: Rules to validate.

    Raises:
        ConfigError: If a rule is invalid.
    """
    for rule in masks:
        try:
            compiled = re.compile(rule.pattern, re.ASCII if rule.ascii else 0)
        except re.error as error:
            raise ConfigError(f"invalid mask rule {rule.name!r}: {error}") from error
        if compiled.search("") is not None:
            raise ConfigError(f"invalid mask rule {rule.name!r}: pattern matches the empty string")


class Masker:
    """Applies masking rules in one left-to-right pass (``docs/ALGORITHM.md`` §2).

    At every position the leftmost match wins; among rules matching at the same position the earliest rule wins. This
    is the semantics of the alternation ``(rule 1)|(rule 2)|...``. Inline regex flags must be scoped, for example
    ``(?i:...)``, and back-references are not supported.
    """

    def __init__(self, rules: Sequence[MaskRule]) -> None:
        """Compile ``rules``.

        Args:
            rules: Masking rules in priority order.

        Raises:
            ConfigError: If a rule is invalid.
        """
        validate_masks(rules)
        self._tokens = [rule.token for rule in rules]
        parts = [f"(?P<_r{i}>(?{'a' if rule.ascii else ''}:{rule.pattern}))" for i, rule in enumerate(rules)]
        self._combined = re.compile("|".join(parts)) if parts else None

    def _replacement(self, match: re.Match[str]) -> str:
        for index, token in enumerate(self._tokens):
            if match.start(f"_r{index}") != -1:
                return token
        raise AssertionError("a match always belongs to one rule")

    def mask(self, text: str) -> str:
        """Return ``text`` with all matches replaced by their tokens.

        Args:
            text: Message text.

        Returns:
            The masked text.
        """
        if self._combined is None:
            return text
        return self._combined.sub(self._replacement, text)
