"""The bridge to the Rust extension ``logfold._core``.

This is the only module allowed to import the extension. It checks that the extension is present and speaks the
expected contract version, makes the calls (one per use case) and turns the exceptions of the extension into the
exceptions of logfold. It knows nothing about the models, the engines or the reporters, which call it.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from logfold.errors import ConfigError, EngineError, FormatError, SourceError, StateError

try:
    import logfold._core as _core  # noqa: PLR0402 - 'from logfold import' would import the package root
except ImportError:
    _core = None  # type: ignore[assignment]

EXPECTED_CORE_API_VERSION = 19


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
    return _call("mine", request, progress)


def match_state(request: dict[str, Any], progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Assign the records of ``request`` to the templates of its saved state in the extension, in one call.

    Args:
        request: The plain-data request of :func:`mine` with a state to load.
        progress: Optional callback receiving the number of input bytes consumed since the previous call.

    Returns:
        The plain-data answer of :func:`mine` plus ``unmatched``: for every run, the records that matched no
        template as ``(token count, records)`` pairs.

    Raises:
        EngineError: If the extension is unavailable.
        ConfigError: If a parameter is invalid or no state is given.
        FormatError: If the format is invalid.
        SourceError: If an input cannot be read.
        StateError: If the state file cannot be used.
    """
    return _call("match_state", request, progress)


def check_state(request: dict[str, Any], progress: Callable[[int], None] | None = None) -> dict[str, Any]:
    """Check the records of ``request`` against its saved state in the extension, in one call.

    Args:
        request: The plain-data request of :func:`match_state`.
        progress: Optional callback receiving the number of input bytes consumed since the previous call.

    Returns:
        The plain-data answer of :func:`match_state` plus ``model`` (the templates of the state with the counts that it
        saved, as one run) and ``new_templates`` (what the records that matched no template form when they are mined by
        themselves).

    Raises:
        EngineError: If the extension is unavailable.
        ConfigError: If a parameter is invalid, no state is given or the state evicts templates.
        FormatError: If the format is invalid.
        SourceError: If an input cannot be read.
        StateError: If the state file cannot be used.
    """
    return _call("check_state", request, progress)


@contextmanager
def _translating() -> Iterator[None]:
    """Turn the exceptions of the extension into the exceptions of logfold."""
    if _core is None:
        raise EngineError("the native extension is unavailable")
    try:
        yield
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from None
    except _core.CoreFormatError as error:
        raise FormatError(str(error)) from None
    except _core.CoreSourceError as error:
        raise SourceError(str(error)) from None
    except _core.CoreStateError as error:
        raise StateError(str(error), hint="mine the state again, or use a state made with the same settings") from None


def _call(name: str, request: dict[str, Any], progress: Callable[[int], None] | None) -> dict[str, Any]:
    with _translating():
        answer: dict[str, Any] = getattr(_core, name)(request, progress)
    return answer


class MinerHandle:
    """A live miner of the extension: one native object that keeps its templates between calls.

    The methods make one native call each, with the GIL released while it works, and are safe to call from several
    threads; records given by several threads are mined in the order in which the calls get the lock.
    """

    def __init__(self, request: dict[str, Any]) -> None:
        """Open the native miner.

        Args:
            request: The plain-data request: ``format``, ``masks``, ``mining`` and ``state``, see
                ``crates/logfold-py/src/miner.rs``.

        Raises:
            EngineError: If the extension is unavailable or speaks another contract version.
            ConfigError: If a parameter is invalid.
            FormatError: If the format is invalid.
            StateError: If the state file to continue from cannot be used.
        """
        require()
        with _translating():
            self._native = _core.NativeMiner(request)

    def add_many(self, records: Iterable[str]) -> int:
        """Mine complete records, one string each, in one call; return how many were mined."""
        batch = list(records)
        with _translating():
            try:
                return int(self._native.add_many(batch))
            except UnicodeEncodeError:
                return int(self._native.add_many(_clean(batch)))

    def add_lines(self, lines: Iterable[str]) -> int:
        """Mine physical lines, joining continuation lines to the record before them; return the records completed."""
        batch = list(lines)
        with _translating():
            try:
                return int(self._native.add_lines(batch))
            except UnicodeEncodeError:
                return int(self._native.add_lines(_clean(batch)))

    def flush(self) -> int:
        """Mine the record that is still open; return how many records were mined (0 or 1)."""
        with _translating():
            return int(self._native.flush())

    def match_many(self, records: Iterable[str], exact: bool = False) -> tuple[list[tuple[str, str]], list[int | None]]:
        """Assign complete records to the templates of the miner without learning, in one call.

        Args:
            records: One string per record.
            exact: A record fits a template only when every constant token of the template equals its token.

        Returns:
            The distinct templates that were hit as ``(id, text)`` pairs, and for every record the index of its
            template in that list, or ``None`` when it fits none.
        """
        batch = list(records)
        with _translating():
            try:
                return self._native.match_many(batch, exact)
            except UnicodeEncodeError:
                return self._native.match_many(_clean(batch), exact)

    def new_templates(self) -> list[str]:
        """Return the texts of the templates created since the previous call, in creation order."""
        with _translating():
            return list(self._native.new_templates())

    def result(self) -> dict[str, Any]:
        """Return the plain-data answer of :func:`mine` for the records mined so far."""
        with _translating():
            answer: dict[str, Any] = self._native.result()
        return answer

    def save_state(self, path: str, state_format: str | None = None) -> None:
        """Write the miner as a state file; ``state_format`` is ``json`` or ``binary``."""
        with _translating():
            self._native.save_state(path, state_format)


class MaskerHandle:
    """The compiled masking rules of the extension, serving any number of texts.

    The rules are applied by an engine that runs in time linear in the text, whatever the patterns are. The handle is
    immutable and safe to share between threads.
    """

    def __init__(self, masks: list[dict[str, Any]]) -> None:
        """Compile the rules.

        Args:
            masks: The masking rules as plain data (``name``, ``pattern``, ``token``, ``ascii``, ``check``).

        Raises:
            EngineError: If the extension is unavailable or speaks another contract version.
            ConfigError: If a rule is invalid.
        """
        require()
        with _translating():
            self._native = _core.NativeMasker(masks)

    def first_layer_is_gated(self) -> bool:
        """Tell whether a text that has none of the literals of the rules skips the regex engine (it is faster)."""
        with _translating():
            return bool(self._native.first_layer_is_gated())

    def mask_many(self, texts: Sequence[str]) -> list[str]:
        """Return the texts with the rules applied; a lone surrogate is read as U+FFFD."""
        batch = list(texts)
        with _translating():
            try:
                masked: list[str] = self._native.mask_many(batch)
            except UnicodeEncodeError:
                masked = self._native.mask_many(_clean(batch))
        return masked


class ExtractorHandle:
    """The compiled masks and delimiters of the extension, serving any number of messages.

    It is immutable and safe to share between threads.
    """

    def __init__(self, masks: list[dict[str, Any]], delimiters: str) -> None:
        """Compile the masks and the delimiters.

        Args:
            masks: The masking rules as plain data (``name``, ``pattern``, ``token``, ``ascii``).
            delimiters: ASCII characters that separate tokens.

        Raises:
            EngineError: If the extension is unavailable or speaks another contract version.
            ConfigError: If a rule or the delimiters are invalid.
        """
        require()
        with _translating():
            self._native = _core.NativeExtractor(masks, delimiters)

    def extract(self, template: str, messages: Sequence[str]) -> list[list[tuple[int, str, str]] | None]:
        """Give the parameters of every message at the variable positions of ``template``.

        Args:
            template: The text of a template (tokens joined by single spaces).
            messages: The messages.

        Returns:
            For every message the list of ``(position, name, value)``, or ``None`` when it does not fit the template.
        """
        batch = list(messages)
        with _translating():
            try:
                found: list[list[tuple[int, str, str]] | None] = self._native.extract(template, batch)
            except UnicodeEncodeError:
                found = self._native.extract(_clean(template), _clean(batch))
        return found


_SURROGATES = re.compile("[\ud800-\udfff]")


def _clean(value: Any) -> Any:
    """Copy ``value`` with every lone surrogate in its strings replaced by U+FFFD, which UTF-8 can hold."""
    if isinstance(value, str):
        return _SURROGATES.sub("\ufffd", value)
    if isinstance(value, list):
        return [_clean(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_clean(item) for item in value)
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items()}
    return value


def _rule_list(rules: Sequence[tuple[str, str]] | None) -> list[tuple[str, str]] | None:
    return None if rules is None else [(left, right) for left, right in rules]


def match_templates(
    kind: str,
    before: Sequence[str],
    after: Sequence[str],
    threshold: float | None = None,
    rules: Sequence[tuple[str, str]] | None = None,
) -> list[tuple[int, int]]:
    """Pair the templates of two runs that occur in one run only, in the extension.

    A lone surrogate in a text has no UTF-8 form and is read as U+FFFD.

    Args:
        kind: ``token_subset``, ``jaccard``, ``jaccard_idf``, ``overlap`` or ``rules``.
        before: Template texts present only in the first run.
        after: Template texts present only in the second run.
        threshold: Minimum similarity of the ``jaccard``, ``jaccard_idf`` and ``overlap`` matchers.
        rules: The ``(left, right)`` template texts of the ``rules`` matcher.

    Returns:
        ``(i, j)`` pairs as ``docs/ALGORITHM.md`` section 10 defines them.

    Raises:
        EngineError: If the extension is unavailable or speaks another contract version.
        ConfigError: If the extension rejects the request.
    """
    require()
    arguments = (kind, list(before), list(after), threshold, _rule_list(rules))
    try:
        try:
            return list(_core.match_templates(*arguments))
        except UnicodeError:
            return list(_core.match_templates(*_clean(arguments)))
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from error


def compare_runs(
    before: tuple[Sequence[str], Sequence[int], int],
    after: tuple[Sequence[str], Sequence[int], int],
    thresholds: tuple[float, int, int],
    matcher: str,
    matcher_threshold: float | None = None,
    rules: Sequence[tuple[str, str]] | None = None,
) -> tuple[list[int], list[int], list[tuple[int, int, float, float, float | None]], int]:
    """Split the templates of two runs into new, disappeared, changed and unchanged, in the extension.

    A lone surrogate in a text has no UTF-8 form and is read as U+FFFD.

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
        EngineError: If the extension is unavailable or speaks another contract version.
        ConfigError: If the extension rejects the request.
        OverflowError: If a count does not fit an unsigned 64-bit integer.
    """
    require()
    arguments = (
        list(before[0]),
        list(before[1]),
        before[2],
        list(after[0]),
        list(after[1]),
        after[2],
        *thresholds,
        matcher,
        matcher_threshold,
        _rule_list(rules),
    )
    try:
        try:
            return _core.compare_runs(*arguments)
        except UnicodeError:
            return _core.compare_runs(*_clean(arguments))
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
    require()
    try:
        answer: dict[str, Any] = _core.inspect_sample(sample, format, keep)
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from None
    except _core.CoreFormatError as error:
        raise FormatError(str(error)) from None
    except _core.CoreSourceError as error:
        raise SourceError(str(error)) from None
    return answer


def render_report(name: str, data: dict[str, Any], options: dict[str, Any]) -> str:
    """Render a pipeline report of a result given as columns, in the extension.

    A lone surrogate in a text has no UTF-8 form and is read as U+FFFD.

    Args:
        name: ``github-summary``, ``junit``, ``chat-message`` or ``prometheus``.
        data: The columns of the result, see ``docs/ALGORITHM.md`` section 12.
        options: ``top`` and, for ``github-summary`` and ``chat-message``, ``max_bytes`` or ``max_chars``.

    Returns:
        The text of the report.

    Raises:
        EngineError: If the extension is unavailable or speaks another contract version.
        ConfigError: If the extension rejects the data, or a count of the result is negative or above 2^64 - 1.
    """
    require()
    try:
        try:
            return _core.render_report(name, data, options)
        except UnicodeError:
            return _core.render_report(name, _clean(data), options)
    except _core.CoreConfigError as error:
        raise ConfigError(str(error)) from error
    except OverflowError as error:
        raise ConfigError(f"a report cannot show the result: {error}") from error


def core_versions() -> dict[str, Any] | None:
    """Return the versions reported by the extension, or ``None`` when it is unavailable."""
    if _core is None:
        return None
    return {"core": _core.__version__, "contract": _core.api_version(), "algo": _core.algo_version()}
