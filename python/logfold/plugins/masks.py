"""The mask sets that ship with logfold: ``default``, ``secrets`` and ``pii``.

``secrets`` and ``pii`` are JSON files in ``mask_data`` (the same format as a user's ``--masks-file``). ``default`` is
the built-in list of ``docs/ALGORITHM.md`` section 2; it always runs last, so selecting it by name changes nothing.
"""

from __future__ import annotations

import json
from importlib import resources

from logfold.config import DEFAULT_MASKS
from logfold.ext.mask_sets import MaskSet

__all__ = ["DEFAULT", "PII", "SECRETS", "builtin_mask_sets"]


def _read(name: str) -> MaskSet:
    raw = resources.files("logfold.plugins").joinpath("mask_data", f"{name}.json").read_bytes()
    return MaskSet.from_dict(json.loads(raw), f"built-in mask set {name!r}")


DEFAULT = MaskSet(
    "default",
    DEFAULT_MASKS,
    description="Numbers, IPs, UUIDs, timestamps, paths and hex values; always applied last.",
)
SECRETS = _read("secrets")
PII = _read("pii")


def builtin_mask_sets() -> tuple[MaskSet, ...]:
    """Return the sets that ship with logfold.

    Returns:
        ``default``, ``secrets`` and ``pii``.
    """
    return (DEFAULT, SECRETS, PII)
