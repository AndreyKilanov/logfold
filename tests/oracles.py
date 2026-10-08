"""Reference implementations of the diff matchers: every pair of templates is compared.

They are the first versions of the matchers, kept as oracles for the native ones: they share no code with the engine.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

WILDCARD = "<*>"


def generalizes(general: list[str], specific: list[str]) -> bool:
    """Tell whether ``general`` has a wildcard or the same token as ``specific`` at every position."""
    return all(g in (WILDCARD, s) for g, s in zip(general, specific, strict=True))


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
            if generalizes(candidate, tokens) or generalizes(tokens, candidate):
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


def _greedy(scored: list[tuple[float, int, int]]) -> list[tuple[int, int]]:
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


def quadratic_overlap(before_only: Sequence[str], after_only: Sequence[str], threshold: float) -> list[tuple[int, int]]:
    """The overlap matcher by its definition: every pair of templates of three words or more is scored."""
    before = [set(text.split()) for text in before_only]
    after = [set(text.split()) for text in after_only]
    scored = [
        (score, i, j)
        for i, left in enumerate(before)
        if len(left) >= 3
        for j, right in enumerate(after)
        if len(right) >= 3
        if (score := len(left & right) / min(len(left), len(right))) >= threshold
    ]
    return _greedy(scored)


def quadratic_jaccard_idf(
    before_only: Sequence[str], after_only: Sequence[str], threshold: float
) -> list[tuple[int, int]]:
    """The jaccard-idf matcher by its definition: every pair is scored, the weights summed in rank order."""
    before = [set(text.split()) for text in before_only]
    after = [set(text.split()) for text in after_only]
    frequency = Counter(word for words in [*before, *after] for word in words)
    scored: list[tuple[float, int, int]] = []
    for i, left in enumerate(before):
        for j, right in enumerate(after):
            shared = union = 0.0
            for word in sorted(left | right, key=lambda w: (frequency[w], w)):
                weight = 1.0 / frequency[word]
                union += weight
                if word in left and word in right:
                    shared += weight
            score = shared / union if union > 0.0 else 0.0
            if score >= threshold:
                scored.append((score, i, j))
    return _greedy(scored)


def _tokens(text: str) -> list[str]:
    return text.split(" ") if text else []


def _agree(pattern: list[str], text: list[str]) -> bool:
    return len(pattern) == len(text) and all(p == t or WILDCARD in (p, t) for p, t in zip(pattern, text, strict=True))


def reference_rules(
    before_only: Sequence[str], after_only: Sequence[str], rules: Sequence[tuple[str, str]]
) -> list[tuple[int, int]]:
    """Apply the rules in order, each in both directions, by testing every template against every rule."""
    before = [_tokens(text) for text in before_only]
    after = [_tokens(text) for text in after_only]
    used_before: set[int] = set()
    used_after: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for left_text, right_text in rules:
        left, right = _tokens(left_text), _tokens(right_text)
        for first, second in ((left, right), (right, left)):
            firsts = [i for i, tokens in enumerate(before) if i not in used_before and _agree(first, tokens)]
            seconds = [j for j, tokens in enumerate(after) if j not in used_after and _agree(second, tokens)]
            for i, j in zip(firsts, seconds, strict=False):
                used_before.add(i)
                used_after.add(j)
                pairs.append((i, j))
    return sorted(pairs)
