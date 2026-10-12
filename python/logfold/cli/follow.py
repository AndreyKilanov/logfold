"""Reading a live stream for ``logfold stream``: a reader thread and a backlog that holds a bounded amount of text."""

from __future__ import annotations

import codecs
import threading
from collections import deque
from typing import BinaryIO

MAX_LINE_CHARS = 1 << 20
BACKLOG_CHARS = 16 << 20
CHUNK_BYTES = 1 << 20


class Backlog:
    """Lines read by a thread and waiting for the miner, holding at most about ``limit`` characters.

    The reader waits while the backlog is full, so the memory of a stream is bounded whatever its speed.
    """

    def __init__(self, limit: int = BACKLOG_CHARS) -> None:
        """Create an empty backlog.

        Args:
            limit: Number of characters after which the reader waits until the miner has taken lines.
        """
        self._limit = limit
        self._lines: deque[str] = deque()
        self._size = 0
        self._finished = False
        self._stopped = False
        self._error: OSError | ValueError | None = None
        self._changed = threading.Condition()

    def put(self, lines: list[str]) -> bool:
        """Add lines, waiting while the backlog is full.

        Args:
            lines: The lines, in the order they were read.

        Returns:
            False when the consumer has stopped and the reader should end.
        """
        with self._changed:
            while self._size >= self._limit and not self._stopped:
                self._changed.wait()
            if self._stopped:
                return False
            self._lines.extend(lines)
            self._size += sum(map(len, lines))
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
                line = self._lines.popleft()
                lines.append(line)
                self._size -= len(line)
            self._changed.notify_all()
            done = self._finished and not self._lines
            if done and self._error is not None:
                if lines:
                    return lines, False
                error, self._error = self._error, None
                raise error
            return lines, done


def read_lines(source: BinaryIO, backlog: Backlog) -> None:
    """Read ``source`` into ``backlog`` as lines until it ends; meant to run in a thread.

    The source is read in chunks of whatever is available, so a live stream is not held back, and a line longer than
    ``MAX_LINE_CHARS`` arrives in pieces. Bytes that are not UTF-8 become U+FFFD.

    Args:
        source: A binary stream.
        backlog: Where the lines go.
    """
    error: OSError | ValueError | None = None
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    read = source.read1 if hasattr(source, "read1") else source.read
    carry = ""
    try:
        while chunk := read(CHUNK_BYTES):
            *complete, carry = (carry + decoder.decode(chunk)).split("\n")
            if len(carry) > MAX_LINE_CHARS:
                complete.append(carry)
                carry = ""
            if complete and not backlog.put(complete):
                return
        tail = carry + decoder.decode(b"", final=True)
        if tail:
            backlog.put([tail])
    except (OSError, ValueError) as caught:
        error = caught
    finally:
        backlog.finish(error)
