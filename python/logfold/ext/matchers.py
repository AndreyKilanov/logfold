"""Diff matcher extension point: decides which templates of two runs are the same template."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


@runtime_checkable
class DiffMatcher(Protocol):
    """Pairs templates that exist in only one run but describe the same event.

    The miner already uses one shared tree for both runs, so templates present in both runs are matched exactly.
    A matcher handles the remainder: ``before_only`` and ``after_only`` hold template texts that appeared in a single
    run. Every returned pair removes a false "disappeared" and a false "new" and compares the pair as one template.

    Attributes:
        name: Matcher name used in :class:`logfold.DiffConfig`.
    """

    name: str

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]:
        """Return index pairs ``(i, j)`` meaning ``before_only[i]`` and ``after_only[j]`` are the same template.

        Args:
            before_only: Template texts present only in the first run.
            after_only: Template texts present only in the second run.

        Returns:
            Pairs in which every index occurs at most once.
        """
        ...
