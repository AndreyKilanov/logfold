"""``logfold stream`` on a pipe that stays open: templates and states appear while the writer is still running."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import requires_native
from logfold.cli.follow import Backlog

pytestmark = requires_native

DEADLINE = 30.0


def start(*arguments: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-I", "-m", "logfold", "stream", "-q", *arguments],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def first_line(process: subprocess.Popen[bytes]) -> bytes:
    assert process.stdout is not None
    box: list[bytes] = []
    reader = threading.Thread(target=lambda: box.append(process.stdout.readline()), daemon=True)  # type: ignore[union-attr]
    reader.start()
    reader.join(DEADLINE)
    assert box, "nothing was printed while the stream was open"
    return box[0]


def test_a_new_template_is_printed_while_the_writer_is_still_running() -> None:
    process = start()
    try:
        assert process.stdin is not None
        process.stdin.write(b"the disk caught fire\n")
        process.stdin.flush()
        assert first_line(process).strip() == b"new  the disk caught fire"
    finally:
        assert process.stdin is not None
        process.stdin.close()
        process.communicate(timeout=DEADLINE)
    assert process.returncode == 0


def test_the_state_is_written_while_the_stream_runs(tmp_path: Path) -> None:
    state = tmp_path / "live.json"
    process = start("--save-state", str(state), "--save-every", "1")
    try:
        assert process.stdin is not None
        process.stdin.write(b"job 1 done\njob 2 done\n")
        process.stdin.flush()
        deadline = time.monotonic() + DEADLINE
        while not state.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert state.exists(), "no state was written before the input ended"
    finally:
        assert process.stdin is not None
        process.stdin.close()
        process.communicate(timeout=DEADLINE)
    assert process.returncode == 0


def test_a_full_backlog_holds_the_reader_until_lines_are_taken() -> None:
    backlog = Backlog(limit=10)
    assert backlog.put("aaaaaaaaaaaa", 12)
    blocked = threading.Thread(target=backlog.put, args=("b", 1), daemon=True)
    blocked.start()
    blocked.join(0.3)
    assert blocked.is_alive()
    lines, finished = backlog.take(10, 1.0)
    assert lines == ["aaaaaaaaaaaa"]
    assert not finished
    blocked.join(DEADLINE)
    assert not blocked.is_alive()


def test_a_stopped_backlog_releases_a_waiting_reader() -> None:
    backlog = Backlog(limit=1)
    backlog.put("x", 5)
    results: list[bool] = []
    waiting = threading.Thread(target=lambda: results.append(backlog.put("y", 1)), daemon=True)
    waiting.start()
    backlog.stop()
    waiting.join(DEADLINE)
    assert results == [False]


def test_the_error_that_ended_the_stream_comes_after_the_lines_before_it() -> None:
    backlog = Backlog()
    backlog.put("last line", 9)
    backlog.finish(OSError("disk gone"))
    assert backlog.take(10, 0.1) == (["last line"], False)
    with pytest.raises(OSError, match="disk gone"):
        backlog.take(10, 0.1)


def test_a_quiet_stream_returns_nothing_and_is_not_finished() -> None:
    backlog = Backlog()
    started = time.monotonic()
    assert backlog.take(10, 0.2) == ([], False)
    assert time.monotonic() - started >= 0.15
    backlog.finish()
    assert backlog.take(10, 0.2) == ([], True)
