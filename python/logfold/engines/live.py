"""The live engine: one native miner that takes records as they come and keeps its templates between calls."""

from __future__ import annotations

from collections.abc import Iterable

from logfold import _bridge
from logfold.config import MiningConfig
from logfold.engines.base import MiningResult, StateRequest
from logfold.engines.native import format_to_dict, mining_to_dicts, state_to_dict, to_result
from logfold.ext.formats import FormatSpec


class LiveMiner:
    """A native miner behind a lock; see :class:`logfold.Miner` for the public class.

    The methods are safe to call from several threads. Records given by several threads are mined in the order in
    which the calls get the lock, so only a single feeder gives a repeatable result.
    """

    def __init__(self, spec: FormatSpec, mining: MiningConfig, state: StateRequest) -> None:
        """Open the miner, empty or continuing from ``state.load``.

        Args:
            spec: Format of the records.
            mining: Mining parameters and masks.
            state: State files: the file to continue from, and the header data of the files that are written.

        Raises:
            EngineError: If the native extension is unavailable.
            ConfigError: If a parameter is invalid.
            FormatError: If the format is invalid.
            StateError: If the state file to continue from cannot be used.
        """
        masks, parameters = mining_to_dicts(mining)
        self._handle = _bridge.MinerHandle(
            {"format": format_to_dict(spec), "masks": masks, "mining": parameters, "state": state_to_dict(state)}
        )

    def add_many(self, records: Iterable[str]) -> int:
        """Mine complete records, one string each; return how many were mined."""
        return self._handle.add_many(records)

    def add_lines(self, lines: Iterable[str]) -> int:
        """Mine physical lines, joining continuation lines to the record before them; return the records completed."""
        return self._handle.add_lines(lines)

    def flush(self) -> int:
        """Mine the record that is still open; return how many records were mined (0 or 1)."""
        return self._handle.flush()

    def match_many(self, records: Iterable[str]) -> tuple[list[tuple[str, str]], list[int | None]]:
        """Assign records to the templates without learning; see :meth:`logfold._bridge.MinerHandle.match_many`."""
        return self._handle.match_many(records)

    def new_templates(self) -> list[str]:
        """Return the texts of the templates created since the previous call, in creation order."""
        return self._handle.new_templates()

    def result(self) -> MiningResult:
        """Return the templates and the counters of the records mined so far."""
        return to_result(self._handle.result())

    def save_state(self, path: str, state_format: str | None) -> None:
        """Write the miner as a state file in ``json`` or ``binary`` form."""
        self._handle.save_state(path, state_format)
