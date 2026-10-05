"""Frozen, validated configuration objects.

The flat keyword arguments of :func:`logfold.analyze` and :func:`logfold.diff` are sugar over these classes.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Literal

from logfold.errors import ConfigError

DEFAULT_CHUNK_BYTES = 64 << 20
HIGH_CARDINALITY_MAX_TEMPLATES = 5_000
EngineName = Literal["auto", "native", "python"]
StrategyName = Literal["auto", "sequential", "chunked"]
ExamplesMode = Literal["raw", "masked", "none"]


@dataclass(frozen=True, slots=True)
class MaskRule:
    r"""A masking rule: every match of ``pattern`` is replaced with ``token`` before mining.

    Attributes:
        name: Rule name used in error messages.
        pattern: Regular expression. It must not match the empty string.
        token: Replacement text, for example ``<IP>``.
        ascii: Compile in ASCII mode so ``\\d``, ``\\w`` and ``\\b`` are ASCII only.
    """

    name: str
    pattern: str
    token: str
    ascii: bool = False


DEFAULT_MASKS: tuple[MaskRule, ...] = (
    MaskRule("uuid", r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>", True),
    MaskRule("ts", r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", "<TS>", True),
    MaskRule("ip", r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "<IP>", True),
    MaskRule("hex", r"\b0[xX][0-9a-fA-F]+\b", "<HEX>", True),
    MaskRule("path", r"(?:/[\w.\-]+){2,}", "<PATH>", True),
    MaskRule("num", r"\b[+-]?\d+(?:\.\d+)?\b", "<NUM>", True),
)


@dataclass(frozen=True, slots=True)
class MiningConfig:
    """Parameters of the template miner (see ``docs/ALGORITHM.md``).

    Attributes:
        depth: Tree depth, at least 3. Follows the Drain3 convention.
        sim_th: Similarity threshold in ``[0, 1]``.
        max_children: Maximum children per tree node, at least 1.
        max_templates: Cap on templates; further records go to overflow templates.
        delimiters: ASCII characters that separate tokens.
        masks: Masking rules applied in order.
    """

    depth: int = 4
    sim_th: float = 0.4
    max_children: int = 100
    max_templates: int = 100_000
    delimiters: str = " \t\n\r"
    masks: tuple[MaskRule, ...] = DEFAULT_MASKS

    def __post_init__(self) -> None:
        """Validate ranges.

        Raises:
            ConfigError: If a value is out of range.
        """
        if self.depth < 3:
            raise ConfigError("depth must be at least 3")
        if not 0.0 <= self.sim_th <= 1.0:
            raise ConfigError("sim_th must be within [0, 1]")
        if self.max_children < 1:
            raise ConfigError("max_children must be at least 1")
        if self.max_templates < 1:
            raise ConfigError("max_templates must be at least 1")
        if not self.delimiters or not self.delimiters.isascii():
            raise ConfigError("delimiters must be a non-empty ASCII string")


@dataclass(frozen=True, slots=True)
class ExecutionConfig:
    """How the work is executed.

    Attributes:
        engine: ``native`` (Rust), ``python`` (reference) or ``auto`` (native when importable).
        strategy: ``sequential``, ``chunked`` or ``auto`` (chunked for large inputs on the native engine, but
            sequential when the first chunk shows that almost every record opens a new template).
        threads: Worker threads for the chunked strategy; ``None`` means all cores.
        chunk_bytes: Chunk size of the chunked strategy.
        warm_start: Chunked strategy only: train the first chunk alone and start every other chunk from a copy of
            its tree. Gives fewer stray templates (closer to the sequential result) at the price of a serial prefix
            of one chunk; the default is off.
    """

    engine: EngineName = "auto"
    strategy: StrategyName = "auto"
    threads: int | None = None
    chunk_bytes: int = DEFAULT_CHUNK_BYTES
    warm_start: bool = False

    def __post_init__(self) -> None:
        """Validate values.

        Raises:
            ConfigError: If a value is out of range.
        """
        if self.engine not in ("auto", "native", "python"):
            raise ConfigError(f"unknown engine {self.engine!r}")
        if self.strategy not in ("auto", "sequential", "chunked"):
            raise ConfigError(f"unknown strategy {self.strategy!r}")
        if self.threads is not None and self.threads < 1:
            raise ConfigError("threads must be at least 1")
        if self.chunk_bytes < 1:
            raise ConfigError("chunk_bytes must be positive")


@dataclass(frozen=True, slots=True)
class DiffConfig:
    """Parameters of the run comparison.

    Attributes:
        threshold_ratio: Minimum change of a template's share to be reported as ``changed`` (at least 1).
        min_count: Minimum record count, in either run, for a template to be reported as ``changed``.
        min_new_count: Minimum record count for a template to be reported as new or disappeared.
        recount: Assign every record of both runs to the finished template tree (consistent, needs a second
            pass over the inputs). Disable only to trade accuracy for speed.
        matcher: Name of the registered diff matcher (``jaccard``, ``token_subset`` or ``exact``).
    """

    threshold_ratio: float = 2.0
    min_count: int = 10
    min_new_count: int = 1
    recount: bool = True
    matcher: str = "jaccard"

    def __post_init__(self) -> None:
        """Validate values.

        Raises:
            ConfigError: If a value is out of range.
        """
        if self.threshold_ratio < 1.0:
            raise ConfigError("threshold_ratio must be at least 1")
        if self.min_count < 0 or self.min_new_count < 0:
            raise ConfigError("min_count and min_new_count must not be negative")


def config_fingerprint(*parts: object) -> str:
    """Return a short stable hash of configuration objects.

    Two results with different fingerprints may use different masks or parameters, so their templates are not
    guaranteed to be comparable.

    Args:
        *parts: Dataclass instances or JSON-compatible values.

    Returns:
        The first 12 hex digits of a SHA-256 over the canonical JSON of ``parts``.
    """

    def plain(value: object) -> object:
        if hasattr(value, "__dataclass_fields__"):
            return asdict(value)  # type: ignore[call-overload]
        return value

    payload = json.dumps([plain(p) for p in parts], sort_keys=True, default=str, ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
