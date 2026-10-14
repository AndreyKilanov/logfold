"""Turning the masks that a caller names into the rules that mining uses."""

from __future__ import annotations

from collections.abc import Sequence

from logfold.config import DEFAULT_MASKS, MaskRule
from logfold.errors import ConfigError
from logfold.ext.mask_sets import MAX_RULES, MaskSet
from logfold.ext.registry import get_mask_set

__all__ = ["DEFAULT_SET_NAME", "MaskSelection", "resolve_masks"]

DEFAULT_SET_NAME = "default"
MaskSelection = Sequence[MaskRule | MaskSet | str]
"""What ``masks=`` takes: rules that replace the defaults, or sets (objects or registered names) that go before them."""


def resolve_masks(
    selection: MaskSelection | str | MaskSet | MaskRule, no_default: bool = False
) -> tuple[MaskRule, ...]:
    """Build the effective list of masking rules from a selection.

    Two kinds of selection exist. A list of :class:`~logfold.config.MaskRule` is the full rule list and replaces the
    defaults (an empty list masks nothing). A list of mask sets, as objects or registered names such as ``"secrets"``,
    puts the rules of the sets first, in the order given, and the default rules last, so that a card number is not
    taken by the rule for plain numbers. The name ``default`` stands for the default rules that always come last.

    Args:
        selection: Rules, or sets and set names; the two cannot be mixed. One item can be given without a list.
        no_default: With sets, leave the default rules out; the result then holds the rules of the sets only.

    Returns:
        The rules in the order in which they are applied.

    Raises:
        ConfigError: If rules and sets are mixed, a set name is unknown (:class:`~logfold.errors.UnknownMaskSetError`),
            or the result has more than 256 rules.
    """
    items = [selection] if isinstance(selection, str | MaskSet | MaskRule) else list(selection)
    if all(isinstance(item, MaskRule) for item in items):
        return tuple(item for item in items if isinstance(item, MaskRule))
    if any(isinstance(item, MaskRule) for item in items):
        raise ConfigError(
            "masks mixes rules with mask sets",
            hint="give either a list of MaskRule (it replaces the defaults) or a list of mask sets and names",
        )
    rules: list[MaskRule] = []
    taken: set[str] = set()
    for item in items:
        if isinstance(item, MaskSet):
            mask_set = item
        elif isinstance(item, str):
            if item == DEFAULT_SET_NAME:
                continue
            mask_set = get_mask_set(item)
        else:
            raise ConfigError(f"a mask set must be a MaskSet or a name, found {item!r}")
        if mask_set.name in taken:
            continue
        taken.add(mask_set.name)
        rules.extend(mask_set.rules)
    if not no_default:
        rules.extend(DEFAULT_MASKS)
    if len(rules) > MAX_RULES:
        raise ConfigError(f"the masks add up to {len(rules)} rules; at most {MAX_RULES} are allowed")
    return tuple(rules)
