"""Diff matchers that ship with logfold as default plugins.

The miner mines both runs into one shared tree, so templates present in both runs are matched by logfold itself. A
matcher only sees the rest, the template texts present in a single run, and may pair them: a reworded message is then
compared as one template instead of being reported as one ``new`` and one ``disappeared`` template.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from itertools import chain

__all__ = ["JaccardMatcher"]


class JaccardMatcher:
    """Pair templates whose sets of words overlap enough (Jaccard similarity).

    The best pairs are taken first, so a template is paired with its closest counterpart. Matchers are created without
    arguments, so the threshold is a class attribute; subclass and register the subclass to change it.

    Attributes:
        name: Name used by ``--matcher`` and :class:`logfold.DiffConfig`.
        threshold: Minimum similarity, from 0 to 1, for two templates to be paired.
    """

    name = "jaccard"
    threshold = 0.6

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates by the overlap of their words.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` meaning ``before_only[i]`` and ``after_only[j]`` are the same template; every index occurs
            at most once.
        """
        before = [set(text.split()) for text in before_only]
        after = [set(text.split()) for text in after_only]
        scored = self._scored(before, after)
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

    def _scored(self, before: list[set[str]], after: list[set[str]]) -> list[tuple[float, int, int]]:
        """Return every ``(score, i, j)`` whose similarity reaches the threshold.

        Pairs are found with prefix filtering: the words of every template are ordered from the rarest to the most
        common, and two sets with similarity ``t`` always share a word among the first ``n - ceil(t * n) + 1`` words
        of each, so only templates that share such a rare word, and whose sizes allow the score (it never exceeds the
        size of the smaller set divided by the size of the larger), are compared. The result is the same as comparing
        all pairs. A threshold above 1, or one that is not a number, is reached by no pair; zero or less pairs
        everything.
        """
        threshold = self.threshold
        if math.isnan(threshold) or threshold > 1:
            return []
        if threshold <= 0:
            return [
                (len(left & right) / union if (union := len(left | right)) else 0.0, i, j)
                for i, left in enumerate(before)
                for j, right in enumerate(after)
            ]
        frequency = Counter(word for words in chain(before, after) for word in words)
        rank = {word: position for position, word in enumerate(sorted(frequency, key=lambda w: (frequency[w], w)))}

        def prefix(words: set[str]) -> list[str]:
            ordered = sorted(words, key=rank.__getitem__)
            keep = len(ordered) - math.ceil(threshold * len(ordered) - 1e-9) + 1
            return ordered[: max(keep, 1)]

        index: dict[str, list[int]] = {}
        for i, left in enumerate(before):
            for word in prefix(left):
                index.setdefault(word, []).append(i)
        scored: list[tuple[float, int, int]] = []
        for j, right in enumerate(after):
            seen: set[int] = set()
            for word in prefix(right):
                for i in index.get(word, ()):
                    if i in seen:
                        continue
                    seen.add(i)
                    smaller, larger = sorted((len(before[i]), len(right)))
                    if smaller / larger < threshold:
                        continue
                    union = len(before[i] | right)
                    score = len(before[i] & right) / union if union else 0.0
                    if score >= threshold:
                        scored.append((score, i, j))
        return scored
