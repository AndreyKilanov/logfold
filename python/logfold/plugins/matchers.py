"""Diff matchers that ship with logfold as default plugins.

The miner mines both runs into one shared tree, so templates present in both runs are matched by logfold itself. A
matcher only sees the rest, the template texts present in a single run, and may pair them: a reworded message is then
compared as one template instead of being reported as one ``new`` and one ``disappeared`` template.

The pairing is done by the native engine in one call (``docs/ALGORITHM.md`` section 10). The classes here hold the
name, the threshold and the rules of a matcher, so that a plugin can subclass one and change them.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Sequence
from pathlib import Path

from logfold import _bridge
from logfold.errors import ConfigError

MAX_RULES_BYTES = 16 << 20
RULE_SEPARATOR = " <=> "

__all__ = ["JaccardIdfMatcher", "JaccardMatcher", "OverlapMatcher", "RulesMatcher", "load_rules"]


class JaccardMatcher:
    """Pair templates whose sets of words overlap enough (Jaccard similarity).

    The best pairs are taken first, so a template is paired with its closest counterpart. Matchers are created without
    arguments, so the threshold is a class attribute; subclass and register the subclass to change it.

    Attributes:
        name: Name used by ``--matcher`` and :class:`logfold.DiffConfig`.
        threshold: Minimum similarity, from 0 to 1, for two templates to be paired. Above 1 or ``nan`` nothing is
            paired; zero or less pairs every pair by score.
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
        return _bridge.match_templates("jaccard", before_only, after_only, float(self.threshold))


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
        """Pair templates by the share of the smaller word set that the larger one holds.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs ``(i, j)`` with every index used at most once, sorted by ``i``.
        """
        return _bridge.match_templates("overlap", before_only, after_only, float(self.threshold))


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
            Pairs ``(i, j)`` with every index used at most once, sorted by ``i``.
        """
        return _bridge.match_templates("jaccard_idf", before_only, after_only, float(self.threshold))


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
        return _bridge.match_templates("rules", before_only, after_only, None, self.rules)


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
