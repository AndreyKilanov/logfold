"""Engine selection."""

from __future__ import annotations

import logging
import os

from logfold import _bridge
from logfold.config import ExecutionConfig
from logfold.engines import native
from logfold.engines.base import Engine
from logfold.engines.python import PythonEngine
from logfold.errors import ConfigError

logger = logging.getLogger("logfold")

ENV_ENGINE = "LOGFOLD_ENGINE"


def select_engine(config: ExecutionConfig) -> Engine:
    """Pick an engine for ``config``.

    ``auto`` prefers the native engine and falls back to the slow reference engine with a warning. The environment
    variable ``LOGFOLD_ENGINE`` overrides ``auto`` (not an explicit choice).

    Args:
        config: Execution configuration.

    Returns:
        An engine instance.

    Raises:
        ConfigError: If the environment variable holds an unknown engine name.
        EngineError: If ``native`` is requested but unavailable.
    """
    choice = config.engine
    if choice == "auto":
        choice = os.environ.get(ENV_ENGINE, "auto")  # type: ignore[assignment]
        if choice not in ("auto", "native", "python"):
            raise ConfigError(f"{ENV_ENGINE} must be auto, native or python, got {choice!r}")
    if choice == "python":
        return PythonEngine()
    if choice == "native":
        return native.NativeEngine()
    if _bridge.is_available():
        return native.NativeEngine()
    logger.warning("native extension unavailable; falling back to the slow pure-Python engine")
    return PythonEngine()
