"""Masking rules: the part of a message that varies is replaced by a stable token before mining."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from functools import lru_cache
from typing import Any

from logfold import _bridge
from logfold.config import DEFAULT_MASKS, MaskRule
from logfold.errors import ConfigError

__all__ = ["DEFAULT_MASKS", "MaskRule", "Masker", "ReferenceMasker", "iban_valid", "luhn_valid", "validate_masks"]

_CARD_DIGITS = range(13, 20)
_IBAN_LENGTH = range(15, 35)


def _plain(rules: Sequence[MaskRule]) -> list[dict[str, Any]]:
    return [
        {"name": rule.name, "pattern": rule.pattern, "token": rule.token, "ascii": rule.ascii, "check": rule.check}
        for rule in rules
    ]


@lru_cache(maxsize=32)
def _compiled(rules: tuple[MaskRule, ...]) -> _bridge.MaskerHandle:
    return _bridge.MaskerHandle(_plain(rules))


def validate_masks(masks: Sequence[MaskRule]) -> None:
    """Check that every rule compiles in the engine that applies it and cannot match the empty string.

    Without the native extension (which mining needs anyway) the patterns are compiled by Python's ``re``, which is
    stricter in some places and laxer in others.

    Args:
        masks: Rules to validate.

    Raises:
        ConfigError: If a rule is invalid.
    """
    if _bridge.is_available():
        _compiled(tuple(masks))
        return
    _validate_with_re(masks)


def _validate_with_re(masks: Sequence[MaskRule]) -> None:
    for rule in masks:
        try:
            compiled = re.compile(rule.pattern, re.ASCII if rule.ascii else 0)
        except re.error as error:
            raise ConfigError(f"invalid mask rule {rule.name!r}: {error}") from error
        if compiled.search("") is not None:
            raise ConfigError(f"invalid mask rule {rule.name!r}: pattern matches the empty string")


def luhn_valid(candidate: str) -> bool:
    """Tell whether ``candidate`` is a card number: 13 to 19 digits (spaces and dashes allowed) with a Luhn checksum.

    Args:
        candidate: The text a rule matched.

    Returns:
        ``True`` when it passes.
    """
    digits = 0
    total = 0
    for char in reversed(candidate):
        if "0" <= char <= "9":
            value = int(char)
            if digits % 2 == 1:
                value = value * 2 - 9 if value > 4 else value * 2
            total += value
            digits += 1
        elif char not in " -":
            return False
    return digits in _CARD_DIGITS and total % 10 == 0


def iban_valid(candidate: str) -> bool:
    """Tell whether ``candidate`` is an IBAN: two letters, two digits, 15 to 34 characters, ISO 7064 mod-97 checksum.

    Args:
        candidate: The text a rule matched; spaces are ignored.

    Returns:
        ``True`` when it passes.
    """
    compact = candidate.replace(" ", "")
    if len(compact) not in _IBAN_LENGTH or not compact.isascii():
        return False
    head, national = compact[:4], compact[4:]
    if not (head[:2].isalpha() and head[2:].isdigit()):
        return False
    if not national.isalnum():
        return False
    return int("".join(str(int(char, 36)) for char in national + head)) % 97 == 1


_CHECKS: dict[str, Callable[[str], bool]] = {"luhn": luhn_valid, "iban": iban_valid}


class _Layer:
    """Rules matched together in one pass, with their checks."""

    def __init__(self, rules: Sequence[MaskRule]) -> None:
        self.tokens = [rule.token for rule in rules]
        self.checks = [None if rule.check is None else _CHECKS[rule.check] for rule in rules]
        parts = [f"(?P<_r{i}>(?{'a' if rule.ascii else ''}:{rule.pattern}))" for i, rule in enumerate(rules)]
        self.combined = re.compile("|".join(parts)) if parts else None

    def _rule(self, match: re.Match[str]) -> int:
        for index in range(len(self.tokens)):
            if match.start(f"_r{index}") != -1:
                return index
        raise AssertionError("a match always belongs to one rule")

    def find(self, text: str, start: int) -> tuple[int, int, int] | None:
        """Return ``(start, end, rule)`` of the leftmost match at or after ``start`` that passes its check."""
        if self.combined is None:
            return None
        while start <= len(text):
            match = self.combined.search(text, start)
            if match is None:
                return None
            rule = self._rule(match)
            check = self.checks[rule]
            if check is not None and not check(match.group()):
                start = match.start() + 1
                continue
            return match.start(), match.end(), rule
        return None

    def substitute(self, text: str) -> str:
        if self.combined is None:
            return text
        return self.combined.sub(lambda match: self.tokens[self._rule(match)], text)


class Masker:
    """Applies masking rules (``docs/ALGORITHM.md`` §2) with the native engine, which runs in time linear in the text.

    A rule list that comes from a file is untrusted, so the rules are never run by Python's backtracking ``re``. The
    compiled rules are kept between instances.
    """

    def __init__(self, rules: Sequence[MaskRule]) -> None:
        """Compile ``rules``.

        Args:
            rules: Masking rules in priority order.

        Raises:
            ConfigError: If a rule is invalid.
            EngineError: If the native extension is unavailable.
        """
        self._handle = _compiled(tuple(rules))

    def mask(self, text: str) -> str:
        """Return ``text`` with all matches replaced by their tokens.

        Args:
            text: Message text.

        Returns:
            The masked text.
        """
        return self._handle.mask_many([text])[0]


class ReferenceMasker:
    """Applies masking rules in pure Python (``docs/ALGORITHM.md`` §2): what the native masker is tested against.

    It uses Python's ``re``, so it is for tests and for patterns you trust, not for rules from a file.

    Rules that stand before the default rules run first, in one left-to-right pass: at every position the leftmost
    match wins, among rules matching at the same position the earliest rule wins, and a match that fails its check is
    skipped (the search goes on from the next character). The default rules, when they end the list, then run over the
    text between those matches. A list without the default rules at its end is one layer. Inline regex flags must be
    scoped, for example ``(?i:...)``, and back-references are not supported.
    """

    def __init__(self, rules: Sequence[MaskRule]) -> None:
        """Compile ``rules``.

        Args:
            rules: Masking rules in priority order.

        Raises:
            ConfigError: If a rule is invalid.
        """
        _validate_with_re(rules)
        count = len(DEFAULT_MASKS)
        split = len(rules) - count if tuple(rules[-count:]) == DEFAULT_MASKS and len(rules) >= count else len(rules)
        self._selected = _Layer(rules[:split])
        self._fallback = _Layer(rules[split:])

    def mask(self, text: str) -> str:
        """Return ``text`` with all matches replaced by their tokens.

        Args:
            text: Message text.

        Returns:
            The masked text.
        """
        first = self._selected.find(text, 0)
        if first is None:
            return self._fallback.substitute(text)
        out: list[str] = []
        cursor = 0
        found: tuple[int, int, int] | None = first
        while found is not None:
            start, end, rule = found
            out.append(self._fallback.substitute(text[cursor:start]))
            out.append(self._selected.tokens[rule])
            cursor = end
            found = self._selected.find(text, end)
        out.append(self._fallback.substitute(text[cursor:]))
        return "".join(out)
