from __future__ import annotations

import os
from pathlib import Path

import pytest

import logfold
from corpora import CORPORA, write
from logfold.engines import native

os.environ.setdefault("LOGFOLD_NO_USER_PLUGINS", "1")  # the tests must not depend on the plugins of whoever runs them

requires_native = pytest.mark.skipif(not native.is_available(), reason="native extension is not built")


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("corpora")
    for name, (generate, _format, _multiline) in CORPORA.items():
        write(directory / f"{name}.log", generate(1500))
    write(directory / "app_crlf.log", CORPORA["app"][0](400), crlf=True)
    write(directory / "app_nonl.log", CORPORA["app"][0](400), final_newline=False)
    write(directory / "app_before.log", CORPORA["app"][0](1200, 11))
    burst = [f"2026-10-04T23:59:{i % 60:02d}Z ERROR database connection lost to replica-{i % 3}" for i in range(80)]
    storm = [f"2026-10-04T23:58:{i % 60:02d}Z INFO cache miss for key k{i}" for i in range(500)]
    write(directory / "app_after.log", CORPORA["app"][0](1800, 12) + burst + storm)
    return directory


@pytest.fixture(scope="session")
def version() -> str:
    return logfold.__version__
