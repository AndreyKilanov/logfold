"""The settings file ``logfold.toml``: what it may hold, how it is found and read, and how it is checked.

The file is data, never code. It has no key that loads a plugin, runs a command or uses the network, so a file that
came with a cloned repository can change the result of a run (that is its purpose) but cannot do more than that.
"""

from __future__ import annotations

import difflib
import os
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from logfold.config import DEFAULT_MASKS, DiffConfig, ExecutionConfig, MaskRule, MiningConfig
from logfold.errors import ConfigError

CONFIG_NAME = "logfold.toml"
ENV_CONFIG = "LOGFOLD_CONFIG"
MAX_CONFIG_BYTES = 64 * 1024
MAX_THREADS = 1024

_Check = Callable[[object], object]


def _integer(minimum: int | None = None, maximum: int | None = None) -> _Check:
    def check(value: object) -> object:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError("an integer")
        if minimum is not None and value < minimum:
            raise ValueError(f"an integer of at least {minimum}")
        if maximum is not None and value > maximum:
            raise ValueError(f"an integer of at most {maximum}")
        return value

    return check


def _number(value: object) -> object:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("a number")
    return float(value)


def _boolean(value: object) -> object:
    if not isinstance(value, bool):
        raise ValueError("true or false")
    return value


def _text(*choices: str) -> _Check:
    def check(value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("a string")
        if choices and value not in choices:
            raise ValueError("one of " + ", ".join(repr(choice) for choice in choices))
        return value

    return check


_TOP = {"format": _text(), "multiline": _boolean}
_MINING = {
    "depth": _integer(3),
    "sim_th": _number,
    "max_children": _integer(1),
    "max_templates": _integer(1),
    "masks": lambda value: value,
}
_EXECUTION = {
    "strategy": _text("auto", "sequential", "chunked"),
    "threads": _integer(1, MAX_THREADS),
    "chunk_mb": _integer(1),
    "warm_start": _boolean,
}
_OUTPUT = {
    "top": _integer(1),
    "examples": _text("raw", "masked", "none"),
    "report": _text(),
    "level": _text(),
    "only_alerts": _boolean,
}
_ANALYZE = {"min_count": _integer(1)}
_DIFF = {
    "threshold_ratio": _number,
    "min_count": _integer(0),
    "min_new_count": _integer(0),
    "significance": _number,
    "matcher": _text(),
    "recount": _boolean,
    "fail_on_new": _boolean,
    "fail_on_new_alerts": _boolean,
}
_SECTIONS: dict[str, dict[str, _Check]] = {
    "mining": _MINING,
    "execution": _EXECUTION,
    "output": _OUTPUT,
    "analyze": _ANALYZE,
    "diff": _DIFF,
}
_MASK_KEYS = {"name": _text(), "pattern": _text(), "token": _text(), "ascii": _boolean}


@dataclass(frozen=True, slots=True)
class Settings:
    """The settings of a run, as a ``logfold.toml`` file holds them.

    Attributes:
        format: Default log format, or ``None`` for ``auto``.
        multiline: Join continuation lines; ``None`` keeps the format's default.
        mining: Mining parameters and masks.
        execution: How the work is executed.
        diff: Parameters of the run comparison.
        top: Rows to print per table (command line only).
        examples: ``raw``, ``masked`` or ``none``.
        report: Reporter name or output form (command line only).
        level: Minimum level of the templates to show (command line only).
        only_alerts: Show only WARN and above (command line only).
        analyze_min_count: ``--min-count`` of ``analyze`` and ``match`` (command line only).
        fail_on_new: ``--fail-on-new`` of ``diff`` (command line only).
        fail_on_new_alerts: ``--fail-on-new-alerts`` of ``diff`` (command line only).
        source: Path of the file that the settings come from, or ``None`` for the built-in defaults.
        given: The ``(section, key)`` pairs that the file set; the top level has the section ``""``.
    """

    format: str | None = None
    multiline: bool | None = None
    mining: MiningConfig = field(default_factory=MiningConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    diff: DiffConfig = field(default_factory=DiffConfig)
    top: int | None = None
    examples: str | None = None
    report: str | None = None
    level: str | None = None
    only_alerts: bool | None = None
    analyze_min_count: int | None = None
    fail_on_new: bool | None = None
    fail_on_new_alerts: bool | None = None
    source: str | None = None
    given: frozenset[tuple[str, str]] = frozenset()

    def command_defaults(self) -> dict[str, dict[str, object]]:
        """Return the defaults of the command line options, per command, for the keys that the file set.

        Returns:
            A mapping of command name to option name to value, for ``Context.default_map`` of the command line app.
        """
        shared: dict[str, object] = {
            name: value
            for name, value in (
                ("format", self.format),
                ("multiline", self.multiline),
                ("top", self.top),
                ("examples", self.examples),
                ("report", self.report),
                ("level", self.level),
                ("only_alerts", self.only_alerts),
            )
            if value is not None
        }
        analyze: dict[str, object] = {
            **shared,
            **({"min_count": self.analyze_min_count} if self.analyze_min_count is not None else {}),
        }
        diff = dict(shared)
        for name in ("threshold_ratio", "min_count", "min_new_count", "significance", "matcher", "recount"):
            if ("diff", name) in self.given:
                diff[name] = getattr(self.diff, name)
        if self.fail_on_new is not None:
            diff["fail_on_new"] = self.fail_on_new
        if self.fail_on_new_alerts is not None:
            diff["fail_on_new_alerts"] = self.fail_on_new_alerts
        inspect: dict[str, object] = {name: shared[name] for name in ("format", "multiline") if name in shared}
        return {"analyze": analyze, "match": dict(analyze), "diff": diff, "inspect": inspect}


def _unknown(source: str, where: str, key: str, known: Mapping[str, object] | list[str]) -> ConfigError:
    names = list(known)
    place = f" in [{where}]" if where else ""
    close = difflib.get_close_matches(key, names, n=1)
    hint = f"did you mean '{close[0]}'?" if close else "known: " + ", ".join(sorted(names))
    return ConfigError(f"{source}: unknown key '{key}'{place}", hint=hint)


def _checked(source: str, where: str, table: Mapping[str, Any], spec: Mapping[str, _Check]) -> dict[str, Any]:
    checked: dict[str, Any] = {}
    for key, value in table.items():
        if key not in spec:
            raise _unknown(source, where, key, spec)
        try:
            checked[key] = spec[key](value)
        except ValueError as error:
            name = f"{where}.{key}" if where else key
            raise ConfigError(f"{source}: '{name}' must be {error}, found {value!r}") from None
    return checked


def _masks(source: str, value: object) -> tuple[MaskRule, ...]:
    if value == "default":
        return DEFAULT_MASKS
    if value == "none":
        return ()
    if not isinstance(value, list):
        raise ConfigError(
            f'{source}: \'mining.masks\' must be "default", "none" or a list of [[mining.masks]] tables, '
            f"found {value!r}"
        )
    rules = []
    for index, item in enumerate(value, start=1):
        where = f"mining.masks #{index}"
        if not isinstance(item, dict):
            raise ConfigError(f"{source}: '{where}' must be a table with name, pattern and token, found {item!r}")
        fields = _checked(source, where, item, _MASK_KEYS)
        missing = [key for key in ("name", "pattern", "token") if key not in fields]
        if missing:
            raise ConfigError(f"{source}: '{where}' needs {', '.join(missing)}")
        rules.append(MaskRule(**fields))
    return tuple(rules)


def _build(source: str, section: str, factory: Callable[[], Any]) -> Any:
    try:
        return factory()
    except ConfigError as error:
        raise ConfigError(f"{source}: [{section}] {error}", hint=error.hint) from None


def parse_settings(data: Mapping[str, Any], source: str) -> Settings:
    """Check the content of a settings file and turn it into :class:`Settings`.

    Args:
        data: The parsed TOML document.
        source: The name of the file, for the messages.

    Returns:
        The settings.

    Raises:
        ConfigError: If a key is unknown, a value has the wrong type or is out of range.
    """
    given: set[tuple[str, str]] = set()
    top: dict[str, Any] = {}
    tables: dict[str, dict[str, Any]] = {}
    for key, value in data.items():
        if key in _SECTIONS:
            if not isinstance(value, dict):
                raise ConfigError(f"{source}: '{key}' must be a table ([{key}]), found {value!r}")
            tables[key] = _checked(source, key, value, _SECTIONS[key])
            given.update((key, name) for name in tables[key])
        elif key in _TOP:
            top.update(_checked(source, "", {key: value}, _TOP))
            given.add(("", key))
        else:
            raise _unknown(source, "", key, [*_TOP, *_SECTIONS])
    mining_table = dict(tables.get("mining", {}))
    masks = _masks(source, mining_table.pop("masks")) if "masks" in mining_table else DEFAULT_MASKS
    execution_table = dict(tables.get("execution", {}))
    if "chunk_mb" in execution_table:
        execution_table["chunk_bytes"] = execution_table.pop("chunk_mb") << 20
    diff_table = tables.get("diff", {})
    diff_keys = {name: diff_table[name] for name in DiffConfig.__dataclass_fields__ if name in diff_table}
    output = tables.get("output", {})
    return Settings(
        format=top.get("format"),
        multiline=top.get("multiline"),
        mining=_build(source, "mining", lambda: MiningConfig(masks=masks, **mining_table)),
        execution=_build(source, "execution", lambda: ExecutionConfig(**execution_table)),
        diff=_build(source, "diff", lambda: DiffConfig(**diff_keys)),
        top=output.get("top"),
        examples=output.get("examples"),
        report=output.get("report"),
        level=output.get("level"),
        only_alerts=output.get("only_alerts"),
        analyze_min_count=tables.get("analyze", {}).get("min_count"),
        fail_on_new=diff_table.get("fail_on_new"),
        fail_on_new_alerts=diff_table.get("fail_on_new_alerts"),
        source=source,
        given=frozenset(given),
    )


def find_config(start: Path | None = None) -> Path | None:
    """Find the ``logfold.toml`` that applies to ``start``.

    The search goes from ``start`` (the current directory by default) up to the first directory that has a ``.git``
    entry, which is searched too, or to the root of the file system. Nothing outside that path is looked at: not the
    home directory and not system folders.

    Args:
        start: The directory to start from.

    Returns:
        The path of the file, or ``None``.
    """
    here = (start or Path.cwd()).resolve()
    for folder in (here, *here.parents):
        candidate = folder / CONFIG_NAME
        if candidate.is_file():
            return candidate
        if (folder / ".git").exists():
            return None
    return None


def read_settings(path: str | os.PathLike[str]) -> Settings:
    """Read and check one settings file.

    Args:
        path: The file.

    Returns:
        The settings.

    Raises:
        ConfigError: If the file cannot be read, is larger than 64 KiB, is not valid TOML or UTF-8, or holds anything
            that :func:`parse_settings` refuses.
    """
    name = os.fspath(path)
    try:
        with open(name, "rb") as handle:
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except OSError as error:
        raise ConfigError(f"cannot read the settings file {name}: {error.strerror or error}") from None
    if len(raw) > MAX_CONFIG_BYTES:
        raise ConfigError(f"{name}: the settings file is larger than {MAX_CONFIG_BYTES // 1024} KiB")
    try:
        data = tomllib.loads(raw.decode("utf-8"))
    except UnicodeDecodeError:
        raise ConfigError(f"{name}: the settings file is not UTF-8") from None
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{name}: not valid TOML: {error}") from None
    except RecursionError:
        raise ConfigError(f"{name}: the settings file is nested too deeply") from None
    return parse_settings(data, name)


def load_config(path: str | os.PathLike[str] | None = None) -> Settings:
    """Load the settings of a run.

    With a ``path`` that file is read. Otherwise the file named by ``LOGFOLD_CONFIG`` is read, or else the first
    ``logfold.toml`` found by :func:`find_config`. When there is none, the built-in defaults are returned.

    Args:
        path: A settings file, or ``None`` to look for one.

    Returns:
        The settings; ``source`` names the file that was read.

    Raises:
        ConfigError: If the file cannot be read or is not valid; see :func:`read_settings`.
    """
    if path is not None:
        return read_settings(path)
    named = os.environ.get(ENV_CONFIG, "")
    if named:
        return read_settings(named)
    found = find_config()
    return read_settings(found) if found is not None else Settings()
