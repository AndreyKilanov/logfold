"""Built-in diff matchers that take no arguments: ``exact`` and ``token_subset``.

The pairing of ``token_subset`` is done by the native engine in one call (``docs/ALGORITHM.md`` section 10).
"""

from __future__ import annotations

from collections.abc import Sequence

from logfold import _bridge


class ExactMatcher:
    """Pairs nothing: a template is the same only when the shared miner put it in the same cluster.

    Attributes:
        name: ``exact``.
    """

    name = "exact"

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Return no pairs.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            An empty list.
        """
        return []


class TokenSubsetMatcher:
    """Pairs templates of equal length when one generalizes the other position by position.

    A wildcard ``<*>`` matches any token. Each template is used at most once; ties go to the candidate with the
    fewest wildcard differences and then the lowest index, so the result is deterministic.

    Attributes:
        name: ``token_subset``.
    """

    name = "token_subset"

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates that are generalizations of each other.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Index pairs ``(i, j)`` with each index used at most once.
        """
        return _bridge.match_templates("token_subset", before_only, after_only)
