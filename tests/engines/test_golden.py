"""The native engine must keep reproducing the golden results of the sequential strategy (docs/ALGORITHM.md)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from conftest import requires_native
from golden_cases import CASES, GOLDEN

pytestmark = requires_native


@pytest.fixture(scope="module")
def golden() -> dict[str, Any]:
    document = json.loads(GOLDEN.read_text(encoding="utf-8"))
    cases: dict[str, Any] = document["cases"]
    return cases


def test_the_golden_file_holds_exactly_the_cases(golden: dict[str, Any]) -> None:
    assert sorted(golden) == sorted(CASES)


@pytest.mark.parametrize("name", sorted(CASES))
def test_native_engine_reproduces_the_golden_case(
    corpus_dir: Path, tmp_path: Path, golden: dict[str, Any], name: str
) -> None:
    assert CASES[name](corpus_dir, tmp_path, "native") == golden[name]


def test_the_golden_cases_are_not_empty(golden: dict[str, Any]) -> None:
    analysed = [case for case in golden.values() if "run" in case]
    assert len(analysed) == len(golden) - 2
    assert all(case["run"]["records"] > 0 for case in analysed)
    assert golden["diff/recount"]["new"] or golden["diff/recount"]["changed"]
    assert golden["parameters/7"]["run"]["overflowed"]
