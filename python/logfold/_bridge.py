"""The bridge to the Rust extension ``logfold._core``.

This is the only module allowed to import the extension. It checks that the extension is present and speaks the
expected contract version, makes the calls (one per use case) and turns the exceptions of the extension into the
exceptions of logfold. It knows nothing about the models, the engines or the reporters, which call it.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from logfold.errors import ConfigError, EngineError, FormatError, SourceError, StateError

try:
    import logfold._core as _core  # noqa: PLR0402 - 'from logfold import' would import the package root
except ImportError:
    _core = None  # type: ignore[assignment]

EXPECTED_CORE_API_VERSION = 9


def is_available() -> bool:
    """Return True when the native extension is importable and speaks the expected contract version."""
    return _core is not None and _core.api_version() == EXPECTED_CORE_API_VERSION


def require() -> None:
    """Check that the extension can be used.

    Raises:
        EngineError: If the extension cannot be imported or speaks another contract version.
    """
    if _core is None:
        raise EngineError("the native extension logfold._core is not available; reinstall a wheel for this platform")
    if _core.api_version() != EXPECTED_CORE_API_VERSION:
        raise EngineError(
            f"native extension speaks contract {_core.api_version()}, expected {EXPECTED_CORE_API_VERSION}; "
            "reinstall logfold"
        )


def mine(request: dict[str, Any], progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Mine the runs of ``request`` in the extension, in one call.

    Args:
        request: The plain-data request, see ``crates/logfold-py/src/convert.rs``.
        progress: Optional callback receiving the number of input bytes consumed since the previous call.

    Returns:
        The plain-data answer: per-run counters, the templates as columns and the metrics.

    Raises:
        EngineError: If the extension is unavailable.
        ConfigError: If a parameter is invalid.
        FormatError: If the format is invalid.
        SourceError: If an input cannot be read.
        StateError: If a state file cannot be used.
    """
    if _core is None:
        raise EngineError("the native extension is unavailable")
    try:
        answer: dict[str, Any] = _core.mine(request, progress)
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from None
    except _core.CoreFormatError as error:
        raise FormatError(str(error)) from None
    except _core.CoreSourceError as error:
        raise SourceError(str(error)) from None
    except _core.CoreStateError as error:
        raise StateError(str(error), hint="mine the state again, or use a state made with the same settings") from None
    return answer


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


def inspect_sample(sample: bytes, format: dict[str, Any], keep: int) -> dict[str, Any]:
    """Read the start of a log with a format in the extension, the way a run reads it.

    Args:
        sample: The lines of the sample, joined with line feeds.
        format: The plain-data format, see ``crates/logfold-py/src/convert.rs``.
        keep: The number of records to return in full.

    Returns:
        The counts of the sample (lines, records, unparsed, levels, first and last time) and the first records.

    Raises:
        EngineError: If the extension is unavailable.
        ConfigError: If the format is invalid.
        FormatError: If the format cannot be compiled.
    """
    if _core is None:
        raise EngineError("the native extension is unavailable")
    try:
        answer: dict[str, Any] = _core.inspect_sample(sample, format, keep)
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from None
    except _core.CoreFormatError as error:
        raise FormatError(str(error)) from None
    return answer


def supports_reports() -> bool:
    """Return True when the extension can render the pipeline reports."""
    return is_available() and hasattr(_core, "render_report")


def render_report(name: str, data: dict[str, Any], options: dict[str, Any]) -> str:
    """Render a pipeline report of a result given as columns, in the extension.

    Args:
        name: ``github-summary``, ``junit``, ``chat-message`` or ``prometheus``.
        data: The columns of the result, see ``docs/ALGORITHM.md`` section 12.
        options: ``top`` and, for ``github-summary`` and ``chat-message``, ``max_bytes`` or ``max_chars``.

    Returns:
        The text, exactly as the pure-Python reporter of the same name writes it.

    Raises:
        ConfigError: If the extension rejects the data.
        UnicodeError: If a text cannot be passed to the extension (for example a lone surrogate).
    """
    if _core is None:
        raise EngineError("the native extension is unavailable")
    try:
        return _core.render_report(name, data, options)
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from error


def core_versions() -> dict[str, Any] | None:
    """Return the versions reported by the extension, or ``None`` when it is unavailable."""
    if _core is None:
        return None
    return {"core": _core.__version__, "contract": _core.api_version(), "algo": _core.algo_version()}
