"""Built-in diff matchers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

WILDCARD = "<*>"


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


def _generalizes(general: list[str], specific: list[str]) -> bool:
    return all(g in (WILDCARD, s) for g, s in zip(general, specific, strict=True))


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
        before_tokens = [text.split(" ") if text else [] for text in before_only]
        by_length: dict[int, list[int]] = defaultdict(list)
        for index, tokens in enumerate(before_tokens):
            by_length[len(tokens)].append(index)
        used: set[int] = set()
        pairs: list[tuple[int, int]] = []
        for j, text in enumerate(after_only):
            tokens = text.split(" ") if text else []
            best: tuple[int, int] | None = None
            for i in by_length.get(len(tokens), ()):
                if i in used:
                    continue
                candidate = before_tokens[i]
                if _generalizes(candidate, tokens) or _generalizes(tokens, candidate):
                    distance = abs(candidate.count(WILDCARD) - tokens.count(WILDCARD))
                    if best is None or distance < best[0]:
                        best = (distance, i)
            if best is not None:
                used.add(best[1])
                pairs.append((best[1], j))
        return pairs
