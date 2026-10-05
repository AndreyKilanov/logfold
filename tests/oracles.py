"""Reference implementations of the diff matchers: every pair of templates is compared.

They are the first versions of the matchers, kept as oracles for the indexed Python matchers and for the native ones.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence

from logfold.comparison.matchers import WILDCARD, _generalizes


def quadratic_token_subset(before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
    """The first implementation, kept as the oracle: every after template is compared with every unused before one."""
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


def quadratic_jaccard(before_only: Sequence[str], after_only: Sequence[str], threshold: float) -> list[tuple[int, int]]:
    """The first implementation of the Jaccard matcher, kept as the oracle: every pair of templates is scored."""
    before = [set(text.split()) for text in before_only]
    after = [set(text.split()) for text in after_only]
    scored: list[tuple[float, int, int]] = []
    for i, left in enumerate(before):
        for j, right in enumerate(after):
            union = len(left | right)
            score = len(left & right) / union if union else 0.0
            if score >= threshold:
                scored.append((score, i, j))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    pairs: list[tuple[int, int]] = []
    used_before: set[int] = set()
    used_after: set[int] = set()
    for _score, i, j in scored:
        if i not in used_before and j not in used_after:
            pairs.append((i, j))
            used_before.add(i)
            used_after.add(j)
    return sorted(pairs)
