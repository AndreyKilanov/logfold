"""The Rust engine: the adapter between the engine port and the native bridge.

It converts requests into plain dictionaries, asks the bridge to run the extension once, and converts the plain-data
answer back into engine DTOs.
"""

from __future__ import annotations

from typing import Any

from logfold import _bridge
from logfold.engines.base import MineRequest, MiningResult, ProgressCallback, RunColumns, RunCounters, TemplateTable
from logfold.errors import FormatError
from logfold.ext.formats import FormatSpec, JsonFormat, PlainFormat, RegexFormat
from logfold.model import RunMetrics


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
    state = request.state
    return {
        "runs": [list(files) for files in request.runs],
        "windows": [tuple(window) for window in request.windows],
        "state": None
        if state is None
        else {
            "load": state.load,
            "save": state.save,
            "format": state.format,
            "config_hash": state.config_hash,
            "masks": state.masks,
            "logfold_version": state.logfold_version,
            "log_format": state.log_format,
        },
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
    runs = tuple(RunCounters(**run) for run in answer["runs"])
    columns = answer["templates"]
    table = TemplateTable(
        ids=columns["ids"], texts=columns["texts"], runs=tuple(RunColumns(**run) for run in columns["runs"])
    )
    unmatched = answer.get("unmatched")
    return MiningResult(
        runs=runs,
        templates=table,
        metrics=RunMetrics(**answer["metrics"]),
        unmatched=None
        if unmatched is None
        else tuple(tuple((int(length), int(records)) for length, records in run) for run in unmatched),
    )


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
        _bridge.require()

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
            StateError: If a state file cannot be used.
        """
        return _to_result(_bridge.mine(request_to_dict(request), progress))

    def match(self, request: MineRequest, progress: ProgressCallback | None = None) -> MiningResult:
        """Assign the records of ``request`` to the templates of its saved state with the Rust engine.

        Args:
            request: What to read, with the state to match against.
            progress: Optional progress callback.

        Returns:
            The templates that were hit, with the statistics of these records only, and the unmatched records.

        Raises:
            ConfigError: If a parameter is invalid.
            FormatError: If the format is invalid.
            SourceError: If an input cannot be read.
            StateError: If the state file cannot be used.
        """
        return _to_result(_bridge.match_state(request_to_dict(request), progress))
