"""Built-in diff matchers."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from itertools import chain

WILDCARD = "<*>"
_NONE: list[int] = []


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


class _Bucket:
    """Templates of one token count, indexed by the literal token or wildcard at every position."""

    __slots__ = ("exact", "members", "wildcard")

    def __init__(self) -> None:
        self.members: list[int] = []
        self.exact: list[dict[str, list[int]]] = []
        self.wildcard: list[list[int]] = []

    def add(self, index: int, tokens: list[str]) -> None:
        if not self.exact:
            self.exact = [{} for _ in tokens]
            self.wildcard = [[] for _ in tokens]
        self.members.append(index)
        for position, token in enumerate(tokens):
            if token == WILDCARD:
                self.wildcard[position].append(index)
            else:
                self.exact[position].setdefault(token, []).append(index)

    def candidates(self, tokens: list[str]) -> Iterable[int]:
        """Return a superset of the templates that generalize ``tokens`` or are generalized by it.

        Both kinds hold, at every position where ``tokens`` has a literal, that literal or a wildcard. The templates
        with such a token at one position are therefore enough, and the shortest of these lists is chosen; the caller
        verifies every candidate. Without a literal in ``tokens`` every template of the bucket is a candidate.
        """
        chosen: tuple[list[int], list[int]] | None = None
        smallest = len(self.members) + 1
        for position, token in enumerate(tokens):
            if token == WILDCARD:
                continue
            literal = self.exact[position].get(token, _NONE)
            wildcard = self.wildcard[position]
            if len(literal) + len(wildcard) < smallest:
                smallest = len(literal) + len(wildcard)
                chosen = (literal, wildcard)
        return self.members if chosen is None else chain(*chosen)


class TokenSubsetMatcher:
    """Pairs templates of equal length when one generalizes the other position by position.

    A wildcard ``<*>`` matches any token. Each template is used at most once; ties go to the candidate with the
    fewest wildcard differences and then the lowest index, so the result is deterministic. Candidates come from an
    index by position and token, so the search does not compare every pair of templates.

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
        buckets: dict[int, _Bucket] = defaultdict(_Bucket)
        for index, tokens in enumerate(before_tokens):
            buckets[len(tokens)].add(index, tokens)
        used: set[int] = set()
        pairs: list[tuple[int, int]] = []
        for j, text in enumerate(after_only):
            tokens = text.split(" ") if text else []
            bucket = buckets.get(len(tokens))
            if bucket is None:
                continue
            wildcards = tokens.count(WILDCARD)
            best: tuple[int, int] | None = None
            for i in bucket.candidates(tokens):
                if i in used:
                    continue
                candidate = before_tokens[i]
                if _generalizes(candidate, tokens) or _generalizes(tokens, candidate):
                    key = (abs(candidate.count(WILDCARD) - wildcards), i)
                    if best is None or key < best:
                        best = key
            if best is not None:
                used.add(best[1])
                pairs.append((best[1], j))
        return pairs
