"""``logfold stream`` on a pipe that stays open: templates and states appear while the writer is still running."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from conftest import requires_native
from logfold.cli.follow import MAX_LINE_CHARS, Backlog, read_lines

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
        process.communicate(timeout=DEADLINE)
    assert process.returncode == 0


def test_a_full_backlog_holds_the_reader_until_lines_are_taken() -> None:
    backlog = Backlog(limit=10)
    assert backlog.put(["aaaaaaaaaaaa"])
    blocked = threading.Thread(target=backlog.put, args=(["b"],), daemon=True)
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
    backlog.put(["xxxxx"])
    results: list[bool] = []
    waiting = threading.Thread(target=lambda: results.append(backlog.put(["y"])), daemon=True)
    waiting.start()
    backlog.stop()
    waiting.join(DEADLINE)
    assert results == [False]


def test_the_error_that_ended_the_stream_comes_after_the_lines_before_it() -> None:
    backlog = Backlog()
    backlog.put(["last line"])
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


class Trickle:
    """A binary source that gives at most ``size`` bytes per read, like a pipe that is written in small pieces."""

    def __init__(self, data: bytes, size: int) -> None:
        self._data = data
        self._size = size

    def read1(self, limit: int) -> bytes:
        count = min(self._size, limit)
        piece, self._data = self._data[:count], self._data[count:]
        return piece


def lines_of(data: bytes, size: int) -> list[str]:
    backlog = Backlog()
    read_lines(Trickle(data, size), backlog)  # type: ignore[arg-type]
    lines: list[str] = []
    while True:
        taken, finished = backlog.take(1000, 0.1)
        lines += taken
        if finished:
            return lines


@pytest.mark.parametrize("size", [1, 2, 3, 7, 1000])
def test_lines_are_cut_correctly_whatever_the_size_of_the_reads(size: int) -> None:
    data = "first\r\nsecond \u00e9 \u4e2d \U0001f600 end\n\nlast without a line feed".encode()
    assert lines_of(data, size) == ["first\r", "second \u00e9 \u4e2d \U0001f600 end", "", "last without a line feed"]


def test_a_stream_that_ends_with_a_line_feed_has_no_empty_last_line() -> None:
    assert lines_of(b"a\nb\n", 2) == ["a", "b"]


def test_bytes_that_are_not_utf8_become_the_replacement_character() -> None:
    assert lines_of(b"caf\xe9 ok\n", 3) == ["caf\ufffd ok"]


def test_an_overlong_line_arrives_in_pieces() -> None:
    lines = lines_of(b"x" * (MAX_LINE_CHARS + 10) + b"\nnext\n", 1 << 20)
    assert sum(map(len, lines[:-1])) == MAX_LINE_CHARS + 10
    assert lines[-1] == "next"
