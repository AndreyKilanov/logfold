"""``docker:`` against a real Docker daemon (opt in: set ``LOGFOLD_TEST_DOCKER=1``; the first run pulls ``alpine``)."""

from __future__ import annotations

import os
import subprocess
import uuid
from collections.abc import Iterator

import pytest

import logfold
from conftest import requires_native
from logfold.errors import SourceError

pytestmark = [
    pytest.mark.skipif(os.environ.get("LOGFOLD_TEST_DOCKER") != "1", reason="set LOGFOLD_TEST_DOCKER=1 to run"),
    requires_native,
]

SCRIPT = (
    "i=0; while [ $i -lt 120 ]; do "
    'echo "2026-10-14 10:00:0$((i%10)) INFO request $i served in $((i*7)) ms"; '
    'echo "2026-10-14 10:00:0$((i%10)) WARN slow query $i" >&2; i=$((i+1)); done'
)


@pytest.fixture
def container() -> Iterator[str]:
    name = f"logfold-validate-{uuid.uuid4().hex[:8]}"
    subprocess.run(
        ["docker", "run", "-d", "--name", name, "alpine:3.20", "sh", "-c", SCRIPT], check=True, capture_output=True
    )
    subprocess.run(["docker", "wait", name], check=True, capture_output=True)
    try:
        yield name
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


def test_the_log_of_a_container_has_both_of_its_streams(container: str) -> None:
    with logfold.fetch(f"docker:{container}") as path:
        result = logfold.analyze(path, format="app")
    assert result.run.name == f"docker:{container}"
    assert result.run.records == 240
    assert sorted(t.text for t in result.templates) == ["request <NUM> served in <NUM> ms", "slow query <NUM>"]


def test_tail_asks_the_program_for_fewer_lines(container: str) -> None:
    with logfold.fetch(f"docker:{container}", tail=10) as path:
        assert len(path.read_text().splitlines()) == 10


def test_a_container_that_does_not_exist_is_an_error_with_the_message_of_docker() -> None:
    with pytest.raises(SourceError, match="No such container"), logfold.fetch("docker:logfold-validate-nosuch"):
        pass
