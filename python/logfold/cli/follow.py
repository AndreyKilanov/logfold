"""Reading a live stream for ``logfold stream``: a reader thread and a backlog that holds a bounded amount of text."""

from __future__ import annotations

import threading
from collections import deque
from typing import BinaryIO

MAX_LINE_BYTES = 1 << 20
BACKLOG_BYTES = 64 << 20


class Backlog:
    """Lines read by a thread and waiting for the miner, holding at most about ``limit`` bytes.

    The reader waits while the backlog is full, so the memory of a stream is bounded whatever its speed.
    """

    def __init__(self, limit: int = BACKLOG_BYTES) -> None:
        """Create an empty backlog.

        Args:
            limit: Number of bytes after which the reader waits until the miner has taken lines.
        """
        self._limit = limit
        self._lines: deque[tuple[str, int]] = deque()
        self._size = 0
        self._finished = False
        self._stopped = False
        self._error: OSError | ValueError | None = None
        self._changed = threading.Condition()

    def put(self, line: str, size: int) -> bool:
        """Add a line, waiting while the backlog is full.

        Args:
            line: The line.
            size: Its size in bytes.

        Returns:
            False when the consumer has stopped and the reader should end.
        """
        with self._changed:
            while self._size >= self._limit and not self._stopped:
                self._changed.wait()
            if self._stopped:
                return False
            self._lines.append((line, size))
            self._size += size
            self._changed.notify_all()
            return True

    def finish(self, error: OSError | ValueError | None = None) -> None:
        """Tell that the stream has ended, with the error that ended it, if any."""
        with self._changed:
            self._finished = True
            self._error = error
            self._changed.notify_all()

    def stop(self) -> None:
        """Tell the reader that nobody is taking lines any more."""
        with self._changed:
            self._stopped = True
            self._changed.notify_all()

    def take(self, maximum: int, timeout: float) -> tuple[list[str], bool]:
        """Take up to ``maximum`` lines, waiting up to ``timeout`` seconds for the first one.

        Args:
            maximum: Most lines to return.
            timeout: Seconds to wait when the backlog is empty.

        Returns:
            The lines (none after a quiet ``timeout``) and whether the stream has ended and nothing is left.

        Raises:
            OSError: When reading the stream failed and the lines before the failure were taken.
        """
        with self._changed:
            if not self._lines and not self._finished:
                self._changed.wait(timeout)
            lines: list[str] = []
            while self._lines and len(lines) < maximum:
                line, size = self._lines.popleft()
                lines.append(line)
                self._size -= size
            self._changed.notify_all()
            done = self._finished and not self._lines
            if done and self._error is not None:
                if lines:
                    return lines, False
                error, self._error = self._error, None
                raise error
            return lines, done


def read_lines(source: BinaryIO, backlog: Backlog) -> None:
    """Read ``source`` line by line into ``backlog`` until it ends; meant to run in a thread.

    A line longer than ``MAX_LINE_BYTES`` arrives in pieces, and bytes that are not UTF-8 become U+FFFD.

    Args:
        source: A binary stream.
        backlog: Where the lines go.
    """
    error: OSError | ValueError | None = None
    try:
        for raw in iter(lambda: source.readline(MAX_LINE_BYTES), b""):
            if not backlog.put(raw.decode("utf-8", errors="replace"), len(raw)):
                break
    except (OSError, ValueError) as caught:
        error = caught
    finally:
        backlog.finish(error)
