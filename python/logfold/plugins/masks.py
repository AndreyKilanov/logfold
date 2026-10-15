"""The mask sets that ship with logfold: ``default``, ``secrets``, ``credentials``, ``pii`` and ``payment``.

The last four are JSON files in ``mask_data`` (the same format as a user's ``--masks-file``), split by what they cost:
every rule of ``secrets`` and ``pii`` starts with, or holds, a literal that the regex engine can search for, so a run
pays little for them; the rules of ``credentials`` (words in any case) and ``payment`` (numbers that can start anywhere)
make the engine read every byte. ``default`` is the built-in list of ``docs/ALGORITHM.md`` section 2; it always runs
last, so selecting it by name changes nothing.
"""

from __future__ import annotations

import json
from importlib import resources

from logfold.config import DEFAULT_MASKS
from logfold.ext.mask_sets import MaskSet

__all__ = ["CREDENTIALS", "DEFAULT", "PAYMENT", "PII", "SECRETS", "builtin_mask_sets"]


def _read(name: str) -> MaskSet:
    raw = resources.files("logfold.plugins").joinpath("mask_data", f"{name}.json").read_bytes()
    return MaskSet.from_dict(json.loads(raw), f"built-in mask set {name!r}")


DEFAULT = MaskSet(
    "default",
    DEFAULT_MASKS,
    version=2,
    description="Numbers, IPs, UUIDs, timestamps, paths and hex values; always applied last.",
)
SECRETS = _read("secrets")
CREDENTIALS = _read("credentials")
PII = _read("pii")
PAYMENT = _read("payment")


def builtin_mask_sets() -> tuple[MaskSet, ...]:
    """Return the sets that ship with logfold.

    Returns:
        ``default``, ``secrets``, ``credentials``, ``pii`` and ``payment``.
    """
    return (DEFAULT, SECRETS, CREDENTIALS, PII, PAYMENT)
