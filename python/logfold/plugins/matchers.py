"""Diff matchers that ship with logfold as default plugins.

The miner mines both runs into one shared tree, so templates present in both runs are matched by logfold itself. A
matcher only sees the rest, the template texts present in a single run, and may pair them: a reworded message is then
compared as one template instead of being reported as one ``new`` and one ``disappeared`` template.
"""

from __future__ import annotations

import math
import os
from collections import Counter
from collections.abc import Iterable, Sequence
from itertools import chain
from pathlib import Path

from logfold.errors import ConfigError

WILDCARD = "<*>"
MIN_OVERLAP_WORDS = 3
MAX_RULES_BYTES = 16 << 20
RULE_SEPARATOR = " <=> "
_SLACK = 1e-9

__all__ = ["JaccardIdfMatcher", "JaccardMatcher", "OverlapMatcher", "RulesMatcher", "load_rules"]


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


def _ranks(before: list[set[str]], after: list[set[str]]) -> tuple[dict[str, int], list[int]]:
    """Rank the words of both runs from the rarest to the most common; return the ranks and the frequency per rank."""
    frequency = Counter(word for words in chain(before, after) for word in words)
    order = sorted(frequency, key=lambda word: (frequency[word], word))
    return {word: position for position, word in enumerate(order)}, [frequency[word] for word in order]


class OverlapMatcher:
    """Pair templates when one contains most of the words of the other (``shared / words of the shorter one``).

    It catches a message that was extended or shortened, where the Jaccard similarity falls because the union grows.
    A template with fewer than three words is never paired, because it is contained in almost any longer one. The best
    pairs are taken first. Matchers are created without arguments, so the threshold is a class attribute.

    Attributes:
        name: Name used by ``--matcher`` and :class:`logfold.DiffConfig`.
        threshold: Minimum score, from 0 to 1, for two templates to be paired.
    """

    name = "overlap"
    threshold = 0.8

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates by the share of the shorter one that the longer one contains.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` meaning ``before_only[i]`` and ``after_only[j]`` are the same template; every index occurs
            at most once, sorted by ``i``.
        """
        before = [set(text.split()) for text in before_only]
        after = [set(text.split()) for text in after_only]
        return _greedy(self._scored(before, after))

    def _scored(self, before: list[set[str]], after: list[set[str]]) -> list[tuple[float, int, int]]:
        """Return every ``(score, i, j)`` that reaches the threshold.

        A pair needs ``ceil(t * smaller)`` shared words, so it shares a word among the first ``n - ceil(t * n) + 1``
        words (rarest first) of its smaller side, whichever side that is. A template of the second run therefore
        probes its own prefix against all words of the first run, and all of its words against the prefixes of the
        first run. The result is the same as scoring all pairs.
        """
        threshold = self.threshold
        if math.isnan(threshold) or threshold > 1:
            return []
        if threshold <= 0:
            return [
                (len(left & right) / min(len(left), len(right)), i, j)
                for i, left in enumerate(before)
                if len(left) >= MIN_OVERLAP_WORDS
                for j, right in enumerate(after)
                if len(right) >= MIN_OVERLAP_WORDS
            ]
        rank, _frequency = _ranks(before, after)

        def keep(size: int) -> int:
            return max(1, min(size, size - math.ceil(threshold * size - _SLACK) + 1))

        everywhere: dict[str, list[int]] = {}
        leading: dict[str, list[int]] = {}
        for i, left in enumerate(before):
            if len(left) < MIN_OVERLAP_WORDS:
                continue
            ordered = sorted(left, key=rank.__getitem__)
            for position, word in enumerate(ordered):
                everywhere.setdefault(word, []).append(i)
                if position < keep(len(ordered)):
                    leading.setdefault(word, []).append(i)
        scored: list[tuple[float, int, int]] = []
        for j, right in enumerate(after):
            if len(right) < MIN_OVERLAP_WORDS:
                continue
            ordered = sorted(right, key=rank.__getitem__)
            probes = chain(
                (i for word in ordered[: keep(len(ordered))] for i in everywhere.get(word, ())),
                (i for word in ordered for i in leading.get(word, ())),
            )
            seen: set[int] = set()
            for i in probes:
                if i in seen:
                    continue
                seen.add(i)
                score = len(before[i] & right) / min(len(before[i]), len(right))
                if score >= threshold:
                    scored.append((score, i, j))
        return scored


class JaccardIdfMatcher:
    """Pair templates by a Jaccard similarity in which a rare word counts more than a common one.

    A word weighs ``1 / n``, where ``n`` is the number of templates, in both lists handed to the matcher, that contain
    it. The score is the weight of the shared words over the weight of all words of both templates, so a message that
    shares only common words with another is not paired with it, which separates the siblings of one family of
    templates. The best pairs are taken first. Matchers are created without arguments, so the threshold is a class
    attribute.

    Attributes:
        name: Name used by ``--matcher`` and :class:`logfold.DiffConfig`.
        threshold: Minimum score, from 0 to 1, for two templates to be paired.
    """

    name = "jaccard-idf"
    threshold = 0.5

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair templates by the weighted overlap of their words.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` meaning ``before_only[i]`` and ``after_only[j]`` are the same template; every index occurs
            at most once, sorted by ``i``.
        """
        before = [set(text.split()) for text in before_only]
        after = [set(text.split()) for text in after_only]
        return _greedy(self._scored(before, after))

    def _scored(self, before: list[set[str]], after: list[set[str]]) -> list[tuple[float, int, int]]:
        """Return every ``(score, i, j)`` that reaches the threshold.

        Sums run in rank order, so the floating-point result is the same in every implementation. Two sets with a
        score of at least ``t`` share their heaviest common word, and the words of each set from that word on weigh at
        least ``t`` times the weight of the set, so only templates that share a word among such leading words, and whose
        weights allow the score (it never exceeds the lighter weight over the heavier), are scored. The result is the
        same as scoring all pairs.
        """
        threshold = self.threshold
        if math.isnan(threshold) or threshold > 1:
            return []
        rank, frequency = _ranks(before, after)
        weight = [1.0 / count for count in frequency]
        left_ranks = [sorted(rank[word] for word in words) for words in before]
        right_ranks = [sorted(rank[word] for word in words) for words in after]
        if threshold <= 0:
            return [
                (_weighted_similarity(weight, left, right), i, j)
                for i, left in enumerate(left_ranks)
                for j, right in enumerate(right_ranks)
            ]
        left_total = [_total(weight, ranks) for ranks in left_ranks]
        index: dict[int, list[int]] = {}
        for i, ranks in enumerate(left_ranks):
            for word in ranks[: _leading(weight, ranks, left_total[i], threshold)]:
                index.setdefault(word, []).append(i)
        scored: list[tuple[float, int, int]] = []
        for j, ranks in enumerate(right_ranks):
            total = _total(weight, ranks)
            seen: set[int] = set()
            for word in ranks[: _leading(weight, ranks, total, threshold)]:
                for i in index.get(word, ()):
                    if i in seen:
                        continue
                    seen.add(i)
                    lighter, heavier = sorted((left_total[i], total))
                    if heavier <= 0.0 or lighter < heavier * threshold * (1.0 - _SLACK):
                        continue
                    score = _weighted_similarity(weight, left_ranks[i], ranks)
                    if score >= threshold:
                        scored.append((score, i, j))
        return scored


def _total(weight: list[float], ranks: list[int]) -> float:
    total = 0.0
    for rank in ranks:
        total += weight[rank]
    return total


def _leading(weight: list[float], ranks: list[int], total: float, threshold: float) -> int:
    """Return how many leading words (heaviest first) of a set must be probed."""
    bound = threshold * total * (1.0 - _SLACK)
    suffix = 0.0
    for position in range(len(ranks) - 1, -1, -1):
        suffix += weight[ranks[position]]
        if suffix >= bound:
            return position + 1
    return 0


def _weighted_similarity(weight: list[float], left: list[int], right: list[int]) -> float:
    """Return the shared weight over the weight of the union, both summed in rank order."""
    a = b = 0
    shared = union = 0.0
    while a < len(left) and b < len(right):
        if left[a] < right[b]:
            union += weight[left[a]]
            a += 1
        elif left[a] > right[b]:
            union += weight[right[b]]
            b += 1
        else:
            both = weight[left[a]]
            shared += both
            union += both
            a += 1
            b += 1
    for rank in left[a:]:
        union += weight[rank]
    for rank in right[b:]:
        union += weight[rank]
    return 0.0 if union <= 0.0 else shared / union


def _greedy(scored: list[tuple[float, int, int]]) -> list[tuple[int, int]]:
    """Take pairs from the highest score, then the lowest first index, then the lowest second index."""
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


def _agree(pattern: list[str], text: list[str]) -> bool:
    return len(pattern) == len(text) and all(p == t or WILDCARD in (p, t) for p, t in zip(pattern, text, strict=True))


def _tokens(text: str) -> list[str]:
    return text.split(" ") if text else []


class RulesMatcher:
    """Pair templates that a list of rules written by the user declares to be the same event.

    A rule is a pair of template texts, as the reports show them (``retry failed after <NUM> attempts``). Both sides are
    split on the single space character, and a token ``<*>`` agrees with any token, also on the template's side, where
    the miner puts it. Rules are tried in order; a rule works in both directions. For a rule ``(left, right)`` the
    unused templates of the first run that agree with ``left`` are paired, in index order, with the unused templates of
    the second run that agree with ``right``; then the same for ``right`` against ``left``.

    Attributes:
        name: ``rules``; ``--matcher rules:FILE`` builds one from a file, see :func:`load_rules`.
        rules: The ``(left, right)`` template texts.
    """

    name = "rules"

    def __init__(self, rules: Iterable[tuple[str, str]] = ()) -> None:
        """Keep the rules.

        Args:
            rules: ``(left, right)`` template texts.
        """
        self.rules = tuple(rules)

    @classmethod
    def from_file(cls, path: str | os.PathLike[str]) -> RulesMatcher:
        """Read the rules of a file with :func:`load_rules`.

        Args:
            path: The rules file.

        Returns:
            The matcher.

        Raises:
            ConfigError: If the file cannot be read or a line is not a rule.
        """
        return cls(load_rules(path))

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Pair the templates that the rules declare to be the same event.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` with every index used at most once, sorted by ``i``.
        """
        before = [_tokens(text) for text in before_only]
        after = [_tokens(text) for text in after_only]
        used_before: set[int] = set()
        used_after: set[int] = set()
        pairs: list[tuple[int, int]] = []
        for left_text, right_text in self.rules:
            left, right = _tokens(left_text), _tokens(right_text)
            for first, second in ((left, right), (right, left)):
                firsts = [i for i, tokens in enumerate(before) if i not in used_before and _agree(first, tokens)]
                seconds = [j for j, tokens in enumerate(after) if j not in used_after and _agree(second, tokens)]
                for i, j in zip(firsts, seconds, strict=False):
                    used_before.add(i)
                    used_after.add(j)
                    pairs.append((i, j))
        return sorted(pairs)


def load_rules(path: str | os.PathLike[str]) -> list[tuple[str, str]]:
    """Read matcher rules from a text file.

    One rule per line, ``TEMPLATE <=> TEMPLATE``; the sides are stripped. Empty lines and lines that start with ``#``
    are ignored. The file is UTF-8 and at most 16 MiB.

    Args:
        path: The rules file.

    Returns:
        The ``(left, right)`` pairs in file order.

    Raises:
        ConfigError: If the file cannot be read, is too large, or a line is not a rule with two non-empty sides.
    """
    file = Path(path)
    try:
        if file.stat().st_size > MAX_RULES_BYTES:
            raise ConfigError(f"the rules file {str(file)!r} is larger than {MAX_RULES_BYTES >> 20} MiB")
        text = file.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as error:
        raise ConfigError(f"cannot read the rules file {str(file)!r}: {error}") from error
    rules: list[tuple[str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        left, separator, right = line.partition(RULE_SEPARATOR)
        left, right = left.strip(), right.strip()
        if not separator or not left or not right:
            raise ConfigError(f"{file}:{number}: a rule is 'TEMPLATE{RULE_SEPARATOR}TEMPLATE' with two non-empty sides")
        rules.append((left, right))
    return rules
