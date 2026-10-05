"""``strategy="auto"`` mines in parallel chunks, but sequentially when the first chunk shows unique messages."""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold
from conftest import requires_native

pytestmark = requires_native

CHUNK = 1 << 20


def _word(n: int) -> str:
    letters = []
    for _ in range(6):
        letters.append(chr(ord("a") + n % 26))
        n //= 26
    return "".join(letters)


def unique_log(tmp_path: Path, lines: int) -> Path:
    path = tmp_path / "unique.log"
    rows = (" ".join(_word(i * (2 * k + 3) + k) for k in range(5)) for i in range(lines))
    path.write_text("".join(f"INFO {row}\n" for row in rows), encoding="utf-8")
    return path


def repetitive_log(tmp_path: Path, lines: int) -> Path:
    path = tmp_path / "repetitive.log"
    shapes = (
        "INFO user u{} logged in",
        "WARN disk usage {}% on /dev/sda1",
        "ERROR request {} failed",
        "INFO heartbeat",
    )
    path.write_text("".join(f"{shapes[i % 4].format(i % 97)}\n" for i in range(lines)), encoding="utf-8")
    return path


def test_unique_messages_are_mined_sequentially(tmp_path: Path) -> None:
    path = unique_log(tmp_path, 60_000)
    auto = logfold.analyze(path, format="plain", chunk_bytes=CHUNK, examples="none")
    sequential = logfold.analyze(path, format="plain", strategy="sequential", examples="none")
    assert auto.metrics.strategy == "sequential"
    assert auto.metrics.threads == 1
    assert [(t.id, t.count) for t in auto.templates] == [(t.id, t.count) for t in sequential.templates]


def test_repetitive_logs_stay_chunked(tmp_path: Path) -> None:
    path = repetitive_log(tmp_path, 120_000)
    result = logfold.analyze(path, format="plain", chunk_bytes=CHUNK, examples="none")
    assert result.metrics.strategy == "chunked"
    assert result.metrics.chunks > 1


@pytest.mark.parametrize("strategy", ["chunked", "sequential"])
def test_an_explicit_strategy_is_never_changed(tmp_path: Path, strategy: str) -> None:
    path = unique_log(tmp_path, 60_000)
    result = logfold.analyze(path, format="plain", strategy=strategy, chunk_bytes=CHUNK, examples="none")
    assert result.metrics.strategy == strategy


def test_diff_of_unique_messages_uses_the_fallback_and_stays_consistent(tmp_path: Path) -> None:
    before = unique_log(tmp_path, 40_000)
    after = tmp_path / "after.log"
    after.write_text(before.read_text(encoding="utf-8"), encoding="utf-8")
    result = logfold.diff(before, after, format="plain", chunk_bytes=CHUNK, examples="none")
    assert result.metrics.strategy == "sequential"
    assert not result.new_templates
    assert not result.disappeared
