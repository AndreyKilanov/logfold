"""Mask sets: named, versioned lists of masking rules that are data, not code.

A set is a JSON file (``docs/schema/mask-set.schema.json``) or a :class:`MaskSet` object. The sets that ship with
logfold are ``secrets`` and ``pii``; further sets come from files (``--masks-file``) or plugins (the entry point group
``logfold.masks``). A set file is untrusted input: its size, its number of rules and the size of its patterns are
limited, and it holds no code.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from logfold.config import MASK_CHECKS, MaskRule
from logfold.errors import ConfigError
from logfold.ext.masks import validate_masks

__all__ = [
    "MAX_FILE_BYTES",
    "MAX_PATTERN_BYTES",
    "MAX_RULES",
    "MaskSet",
    "load_mask_set",
    "mask_fingerprint",
]

MAX_RULES = 256
MAX_PATTERN_BYTES = 4096
MAX_FILE_BYTES = 1 << 20
_SET_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_RULE_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
_TOKEN = re.compile(r"<[A-Z][A-Z0-9_]{0,29}>")
_SET_KEYS = ("$schema", "name", "version", "description", "rules")
_RULE_KEYS = ("name", "pattern", "token", "ascii", "check")


def _rule_to_dict(rule: MaskRule) -> dict[str, Any]:
    plain: dict[str, Any] = {"name": rule.name, "pattern": rule.pattern, "token": rule.token, "ascii": rule.ascii}
    if rule.check is not None:
        plain["check"] = rule.check
    return plain


def mask_fingerprint(rules: Sequence[MaskRule]) -> str:
    """Return the identity of an ordered list of masking rules.

    Args:
        rules: The effective rules, in the order in which they are applied.

    Returns:
        The first 16 hex digits of a SHA-256 over the canonical JSON of the rules. A change of any pattern, token, flag
        or check, or of the order, gives another value.
    """
    payload = json.dumps([_rule_to_dict(rule) for rule in rules], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class MaskSet:
    """A named, versioned list of masking rules.

    The set is applied before the default rules (see ``docs/ALGORITHM.md`` section 2), so its tokens must not be
    changed by them. Rules are tried in order; at one position the earliest rule wins.

    Attributes:
        name: Lower-case name, up to 32 characters of ``a-z``, digits, ``_`` and ``-``; it is what ``--masks`` takes.
        rules: The rules, 1 to 256 of them. Rule names are unique; a token looks like ``<NAME>`` with capital letters,
            digits and ``_``, at most 32 bytes; a pattern is at most 4096 bytes and cannot match the empty string.
        version: Whole number that grows when the content of the set changes.
        description: One line about the set.

    Raises:
        ConfigError: If a value breaks the rules above.
    """

    name: str
    rules: tuple[MaskRule, ...]
    version: int = 1
    description: str = ""

    def __post_init__(self) -> None:
        """Validate the set.

        Raises:
            ConfigError: If the name, the version or a rule is invalid.
        """
        object.__setattr__(self, "rules", tuple(self.rules))
        if not isinstance(self.name, str) or _SET_NAME.fullmatch(self.name) is None:
            raise ConfigError(
                f"invalid mask set name {self.name!r}",
                hint="use lower-case letters, digits, '_' and '-', starting with a letter, up to 32 characters",
            )
        where = f"mask set {self.name!r}"
        if isinstance(self.version, bool) or not isinstance(self.version, int) or self.version < 1:
            raise ConfigError(f"{where}: version must be a whole number, at least 1")
        if not 1 <= len(self.rules) <= MAX_RULES:
            raise ConfigError(f"{where}: it needs 1 to {MAX_RULES} rules, found {len(self.rules)}")
        seen: set[str] = set()
        for rule in self.rules:
            if not isinstance(rule, MaskRule):
                raise ConfigError(f"{where}: every rule must be a MaskRule, found {rule!r}")
            if _RULE_NAME.fullmatch(rule.name) is None:
                raise ConfigError(f"{where}: invalid rule name {rule.name!r}")
            if rule.name in seen:
                raise ConfigError(f"{where}: the rule name {rule.name!r} is used twice")
            seen.add(rule.name)
            if _TOKEN.fullmatch(rule.token) is None:
                raise ConfigError(
                    f"{where}, rule {rule.name!r}: invalid token {rule.token!r}",
                    hint="a token looks like <NAME>: capital letters, digits and '_', at most 32 bytes in all",
                )
            if len(rule.pattern.encode("utf-8")) > MAX_PATTERN_BYTES:
                raise ConfigError(f"{where}, rule {rule.name!r}: the pattern is longer than {MAX_PATTERN_BYTES} bytes")
        validate_masks(self.rules)

    @property
    def fingerprint(self) -> str:
        """The identity of the rules of the set, see :func:`mask_fingerprint`."""
        return mask_fingerprint(self.rules)

    def to_dict(self) -> dict[str, Any]:
        """Return the set as the plain data of a set file.

        Returns:
            A dict with ``name``, ``version``, ``description`` and ``rules``.
        """
        return {
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "rules": [_rule_to_dict(rule) for rule in self.rules],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any], source: str = "mask set") -> MaskSet:
        """Build a set from the plain data of a set file.

        Args:
            data: The parsed JSON document.
            source: Where it comes from, for the messages.

        Returns:
            The set.

        Raises:
            ConfigError: If a key is unknown, a value has the wrong type or the set is invalid.
        """
        if not isinstance(data, Mapping):
            raise ConfigError(f"{source}: a mask set must be a JSON object")
        _check_keys(source, "", data, _SET_KEYS)
        for key in ("name", "rules"):
            if key not in data:
                raise ConfigError(f"{source}: the key {key!r} is missing")
        raw_rules = data["rules"]
        if not isinstance(raw_rules, list):
            raise ConfigError(f"{source}: 'rules' must be a list")
        if len(raw_rules) > MAX_RULES:
            raise ConfigError(f"{source}: at most {MAX_RULES} rules are allowed, found {len(raw_rules)}")
        rules = tuple(_rule_from_dict(item, index, source) for index, item in enumerate(raw_rules, start=1))
        description = data.get("description", "")
        if not isinstance(description, str):
            raise ConfigError(f"{source}: 'description' must be text")
        try:
            return cls(name=data["name"], rules=rules, version=data.get("version", 1), description=description)
        except ConfigError as error:
            raise ConfigError(f"{source}: {error}", hint=error.hint) from None


def _check_keys(source: str, where: str, data: Mapping[str, Any], allowed: Sequence[str]) -> None:
    for key in data:
        if key not in allowed:
            place = f" in {where}" if where else ""
            raise ConfigError(f"{source}: unknown key {key!r}{place}", hint=f"allowed keys: {', '.join(allowed)}")


def _rule_from_dict(item: object, index: int, source: str) -> MaskRule:
    where = f"rule #{index}"
    if not isinstance(item, Mapping):
        raise ConfigError(f"{source}: {where} must be a JSON object")
    _check_keys(source, where, item, _RULE_KEYS)
    for key in ("name", "pattern", "token"):
        if not isinstance(item.get(key), str):
            raise ConfigError(f"{source}: {where} needs the text key {key!r}")
    ascii_only = item.get("ascii", True)
    if not isinstance(ascii_only, bool):
        raise ConfigError(f"{source}: {where}: 'ascii' must be true or false")
    check = item.get("check")
    if check is not None and (not isinstance(check, str) or check not in MASK_CHECKS):
        raise ConfigError(f"{source}: {where}: 'check' must be one of {', '.join(MASK_CHECKS)}")
    return MaskRule(item["name"], item["pattern"], item["token"], ascii_only, check)


def load_mask_set(path: str | os.PathLike[str]) -> MaskSet:
    """Read a mask set from a JSON file.

    The file is untrusted: it must be at most 1 MiB, it holds data only, and its patterns are compiled by linear-time
    engines. The name of the file does not matter, the set is named by its ``name`` key.

    Args:
        path: The set file.

    Returns:
        The set.

    Raises:
        ConfigError: If the file cannot be read, is too large, is not valid JSON or does not describe a valid set.
    """
    file = Path(path)
    try:
        with file.open("rb") as handle:
            raw = handle.read(MAX_FILE_BYTES + 1)
    except OSError as error:
        raise ConfigError(f"cannot read the mask set file {file}: {error.strerror or error}") from None
    if len(raw) > MAX_FILE_BYTES:
        raise ConfigError(f"{file}: a mask set file may be at most {MAX_FILE_BYTES} bytes")
    try:
        data = json.loads(raw)
    except (ValueError, RecursionError) as error:
        raise ConfigError(f"{file}: not valid JSON: {error}") from None
    return MaskSet.from_dict(data, str(file))
