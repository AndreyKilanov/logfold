"""Facts about the native engine that the golden cases do not cover (docs/ALGORITHM.md)."""

from __future__ import annotations

from pathlib import Path

import logfold
from conftest import requires_native
from logfold import ExecutionConfig, _core
from logfold.config import DEFAULT_MASKS

pytestmark = requires_native


def test_invalid_utf8_does_not_break_the_run(tmp_path: Path) -> None:
    path = tmp_path / "bad.log"
    path.write_bytes(b"ok line one\nbad \xff\xfe bytes here\nok line two\n")
    result = logfold.analyze(str(path), format="plain", engine="native", strategy="sequential")
    assert result.run.records == 3


def test_the_default_masks_of_the_two_layers_are_in_sync() -> None:
    native_masks = _core.default_masks()
    assert [(m["name"], m["pattern"], m["token"], m["ascii"]) for m in native_masks] == [
        (m.name, m.pattern, m.token, m.ascii) for m in DEFAULT_MASKS
    ]


def test_execution_config_object_is_honoured(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app", execution=ExecutionConfig(engine="native"))
    assert result.metrics.engine == "native"
