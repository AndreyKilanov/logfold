"""Engine selection."""

from __future__ import annotations

import os
import warnings

from logfold.config import ExecutionConfig
from logfold.engines.base import Engine
from logfold.engines.native import NativeEngine
from logfold.errors import ConfigError

ENV_ENGINE = "LOGFOLD_ENGINE"
ENGINE_NAMES = ("auto", "native", "python")


def select_engine(config: ExecutionConfig) -> Engine:
    """Pick the engine for ``config``.

    The Rust engine is the only one. ``python``, the name of the removed reference engine, is still accepted and runs
    the Rust engine with a deprecation warning. The environment variable ``LOGFOLD_ENGINE`` is read when the
    configuration says ``auto``.

    Args:
        config: Execution configuration.

    Returns:
        The native engine.

    Raises:
        ConfigError: If the environment variable holds an unknown engine name.
        EngineError: If the native extension is unavailable or speaks another contract version.
    """
    choice = config.engine
    if choice == "auto":
        choice = os.environ.get(ENV_ENGINE, "auto")  # type: ignore[assignment]
        if choice not in ENGINE_NAMES:
            raise ConfigError(f"{ENV_ENGINE} must be auto, native or python, got {choice!r}")
    if choice == "python":
        warnings.warn(
            "the pure-Python engine has been removed; engine='python' runs the native engine and will be refused "
            "in a later release",
            DeprecationWarning,
            stacklevel=2,
        )
    return NativeEngine()
