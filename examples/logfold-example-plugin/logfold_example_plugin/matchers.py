"""Diff matchers: decide which templates of two runs are the same template.

The miner mines both runs into one shared tree, so templates present in both runs are matched by logfold itself. A
matcher only sees the rest, the template texts present in a single run, and may pair them: a reworded message is then
compared as one template (``changed``) instead of being reported as one ``new`` and one ``disappeared`` template.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = ["FirstWordMatcher", "JaccardMatcher"]


class FirstWordMatcher:
    """Pair templates that start with the same word.

    Attributes:
        name: Name used by ``--matcher`` and :class:`logfold.DiffConfig`.
    """

    name = "first_word"

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates by their first word.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` meaning ``before_only[i]`` and ``after_only[j]`` are the same template; every index occurs
            at most once.
        """
        pairs: list[tuple[int, int]] = []
        used: set[int] = set()
        for j, text in enumerate(after_only):
            for i, other in enumerate(before_only):
                if i not in used and other.split()[:1] == text.split()[:1]:
                    pairs.append((i, j))
                    used.add(i)
                    break
        return pairs


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
        scored: list[tuple[float, int, int]] = []
        for i, left in enumerate(before):
            for j, right in enumerate(after):
                union = len(left | right)
                score = len(left & right) / union if union else 0.0
                if score >= self.threshold:
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
