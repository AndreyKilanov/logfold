"""Adapter over the Rust extension ``logfold._core``.

This is the only module allowed to import the extension. It converts requests into plain dictionaries, calls the
engine once, and converts the plain-data answer back into engine DTOs.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from logfold.engines.base import MineRequest, MiningResult, ProgressCallback, RunColumns, RunInfo, TemplateTable
from logfold.errors import ConfigError, EngineError, FormatError, SourceError
from logfold.ext.formats import FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.model import RunMetrics

try:
    import logfold._core as _core  # noqa: PLR0402 - 'from logfold import' would import the package root
except ImportError:
    _core = None  # type: ignore[assignment]

EXPECTED_CORE_API_VERSION = 6


def is_available() -> bool:
    """Return True when the native extension is importable and speaks the expected contract version."""
    return _core is not None and _core.api_version() == EXPECTED_CORE_API_VERSION


def supports_matching() -> bool:
    """Return True when the extension can pair templates (older builds of the extension lack the function)."""
    return is_available() and hasattr(_core, "match_templates")


def match_templates(
    kind: str,
    before: Sequence[str],
    after: Sequence[str],
    threshold: float | None = None,
    rules: Sequence[tuple[str, str]] | None = None,
) -> list[tuple[int, int]]:
    """Pair the templates of two runs that occur in one run only, in the extension.

    Args:
        kind: ``token_subset``, ``jaccard``, ``jaccard_idf``, ``overlap`` or ``rules``.
        before: Template texts present only in the first run.
        after: Template texts present only in the second run.
        threshold: Minimum similarity of the ``jaccard``, ``jaccard_idf`` and ``overlap`` matchers.
        rules: The ``(left, right)`` template texts of the ``rules`` matcher.

    Returns:
        ``(i, j)`` pairs, exactly as the pure-Python matcher of the same name returns them.

    Raises:
        ConfigError: If the extension rejects the request.
        UnicodeError: If a text cannot be passed to the extension (for example a lone surrogate).
    """
    if _core is None:
        raise EngineError("the native extension is unavailable")
    try:
        return list(_core.match_templates(kind, list(before), list(after), threshold, _rule_list(rules)))
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from error


def _rule_list(rules: Sequence[tuple[str, str]] | None) -> list[tuple[str, str]] | None:
    return None if rules is None else list(rules)


def supports_comparison() -> bool:
    """Return True when the extension can classify the templates of two runs."""
    return is_available() and hasattr(_core, "compare_runs")


def compare_runs(
    before: tuple[Sequence[str], Sequence[int], int],
    after: tuple[Sequence[str], Sequence[int], int],
    thresholds: tuple[float, int, int],
    matcher: str,
    matcher_threshold: float | None = None,
    rules: Sequence[tuple[str, str]] | None = None,
) -> tuple[list[int], list[int], list[tuple[int, int, float, float, float | None]], int]:
    """Split the templates of two runs into new, disappeared, changed and unchanged, in the extension.

    Args:
        before: Texts, counts and total records of the first run.
        after: Texts, counts and total records of the second run.
        thresholds: ``threshold_ratio``, ``min_count`` and ``min_new_count``.
        matcher: ``exact``, ``token_subset``, ``jaccard``, ``jaccard_idf``, ``overlap`` or ``rules``.
        matcher_threshold: Minimum similarity of the ``jaccard``, ``jaccard_idf`` and ``overlap`` matchers.
        rules: The ``(left, right)`` template texts of the ``rules`` matcher.

    Returns:
        Indices of new and disappeared templates, ``(before, after, before share, after share, ratio)`` of the
        changed ones, and the number of unchanged ones; see ``docs/ALGORITHM.md`` section 11.

    Raises:
        ConfigError: If the extension rejects the request.
        UnicodeError: If a text cannot be passed to the extension (for example a lone surrogate).
        OverflowError: If a count does not fit an unsigned 64-bit integer.
    """
    if _core is None:
        raise EngineError("the native extension is unavailable")
    try:
        return _core.compare_runs(
            list(before[0]), list(before[1]), before[2], list(after[0]), list(after[1]), after[2], *thresholds,
            matcher, matcher_threshold, _rule_list(rules),
        )  # fmt: skip
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from error


def core_versions() -> dict[str, Any] | None:
    """Return the versions reported by the extension, or ``None`` when it is unavailable."""
    if _core is None:
        return None
    return {"core": _core.__version__, "contract": _core.api_version(), "algo": _core.algo_version()}


def format_to_dict(spec: FormatSpec) -> dict[str, Any]:
    """Convert a format specification into the plain-data form understood by the extension.

    Args:
        spec: Declarative format specification.

    Returns:
        A dictionary with a ``kind`` key and the parameters of that kind.

    Raises:
        FormatError: If the specification type is unknown.
    """
    if isinstance(spec, PlainFormat):
        return {"kind": "plain", "record_start": spec.record_start, "ts_format": None, "multiline": spec.multiline}
    if isinstance(spec, JsonFormat):
        return {
            "kind": "json",
            "message_keys": list(spec.message_keys),
            "time_keys": list(spec.time_keys),
            "level_keys": list(spec.level_keys),
            "ts_format": spec.ts_format,
            "multiline": False,
        }
    if isinstance(spec, RegexFormat):
        return {
            "kind": "regex",
            "pattern": spec.pattern,
            "message_group": spec.message_group,
            "time_group": spec.time_group,
            "level_group": spec.level_group,
            "ts_format": spec.ts_format,
            "multiline": spec.multiline,
        }
    raise FormatError(f"unsupported format specification {spec!r}")


def request_to_dict(request: MineRequest) -> dict[str, Any]:
    """Convert an engine request into the plain-data form understood by the extension.

    Args:
        request: Engine request.

    Returns:
        A dictionary matching ``crates/logfold-py/src/convert.rs``.
    """
    mining = request.mining
    execution: dict[str, Any] = {
        "strategy": request.strategy,
        "chunk_bytes": request.chunk_bytes,
        "warm_start": request.warm_start,
    }
    if request.threads is not None:
        execution["threads"] = request.threads
    return {
        "runs": [list(files) for files in request.runs],
        "windows": [tuple(window) for window in request.windows],
        "format": format_to_dict(request.format),
        "masks": [
            {"name": rule.name, "pattern": rule.pattern, "token": rule.token, "ascii": rule.ascii}
            for rule in mining.masks
        ],
        "mining": {
            "depth": mining.depth,
            "sim_th": mining.sim_th,
            "max_children": mining.max_children,
            "max_templates": mining.max_templates,
            "delimiters": mining.delimiters,
        },
        "execution": execution,
        "recount": request.recount,
    }


def _to_result(answer: dict[str, Any]) -> MiningResult:
    runs = tuple(RunInfo(**run) for run in answer["runs"])
    columns = answer["templates"]
    table = TemplateTable(
        ids=columns["ids"], texts=columns["texts"], runs=tuple(RunColumns(**run) for run in columns["runs"])
    )
    return MiningResult(runs=runs, templates=table, metrics=RunMetrics(**answer["metrics"]))


class NativeEngine:
    """The Rust engine.

    Attributes:
        name: ``native``.
    """

    name = "native"

    def __init__(self) -> None:
        """Check that the extension is present.

        Raises:
            EngineError: If the extension cannot be imported or has an incompatible version.
        """
        if _core is None:
            raise EngineError(
                "the native extension logfold._core is not available; reinstall a wheel for this platform"
            )
        if _core.api_version() != EXPECTED_CORE_API_VERSION:
            raise EngineError(
                f"native extension speaks contract {_core.api_version()}, expected {EXPECTED_CORE_API_VERSION}; "
                "reinstall logfold"
            )

    def mine(self, request: MineRequest, progress: ProgressCallback | None = None) -> MiningResult:
        """Mine ``request`` with the Rust engine.

        Args:
            request: What to mine.
            progress: Optional progress callback.

        Returns:
            Templates with per-run statistics.

        Raises:
            ConfigError: If a parameter is invalid.
            FormatError: If the format is invalid.
            SourceError: If an input cannot be read.
        """
        assert _core is not None
        try:
            answer = _core.mine(request_to_dict(request), progress)
        except _core.CoreConfigError as error:
            raise ConfigError(str(error)) from None
        except _core.CoreFormatError as error:
            raise FormatError(str(error)) from None
        except _core.CoreSourceError as error:
            raise SourceError(str(error)) from None
        return _to_result(answer)
