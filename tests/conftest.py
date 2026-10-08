from __future__ import annotations

import os
from pathlib import Path

import pytest

import logfold
from corpora import write_corpus_dir
from logfold.engines import native

os.environ.setdefault("LOGFOLD_NO_USER_PLUGINS", "1")  # the tests must not depend on the plugins of whoever runs them

requires_native = pytest.mark.skipif(not native.is_available(), reason="native extension is not built")


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("corpora")
    write_corpus_dir(directory)
    return directory


@pytest.fixture(scope="session")
def version() -> str:
    return logfold.__version__
