"""Masking rules: the part of a message that varies is replaced by a stable token before mining."""

from __future__ import annotations

import re

from logfold.config import DEFAULT_MASKS, MaskRule
from logfold.errors import ConfigError

__all__ = ["DEFAULT_MASKS", "MaskRule", "validate_masks"]


def validate_masks(masks: tuple[MaskRule, ...]) -> None:
    """Check that every rule compiles and cannot match the empty string.

    Args:
        masks: Rules to validate.

    Raises:
        ConfigError: If a rule is invalid.
    """
    for rule in masks:
        try:
            compiled = re.compile(rule.pattern, re.ASCII if rule.ascii else 0)
        except re.error as error:
            raise ConfigError(f"invalid mask rule {rule.name!r}: {error}") from error
        if compiled.search("") is not None:
            raise ConfigError(f"invalid mask rule {rule.name!r}: pattern matches the empty string")
