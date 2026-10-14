"""Reading a log straight from the user's own ``docker``, ``kubectl`` or ``journalctl``.

Nothing here runs unless a caller names a source explicitly. The program is started without a shell, with its input
closed, under a time limit and an output limit; its output goes to a private temporary file that is removed when the
caller is done.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO

from logfold.errors import ConfigError, SourceError
from logfold.ext.labels import clear_label, set_label
from logfold.ext.registry import get_source, source_names
from logfold.ext.sources import SourceOptions
from logfold.ext.text import printable

DEFAULT_TIMEOUT = 300.0
"""Seconds that the program may run before it is stopped."""

DEFAULT_MAX_BYTES = 1 << 30
"""Bytes of output that are kept before the program is stopped (1 GiB)."""

_CHUNK = 1 << 20
_STDERR_KEEP = 4096
_MESSAGE_CHARS = 500
_SUFFIXES = ("",) if sys.platform != "win32" else (".exe", ".com")


def split_source(text: str) -> tuple[str, str] | None:
    r"""Split ``docker:web`` into the source name and the target.

    A text is a source only when the part before the first colon is a registered source name, so file paths (a
    Windows drive such as ``C:\\log`` included) are never taken for one. A file that has such a name is written
    ``./docker:web``.

    Args:
        text: A command-line argument that is a log path or a source.

    Returns:
        ``(name, target)``, or ``None`` when the text is not a source.
    """
    name, colon, target = text.partition(":")
    if not colon or not target or name not in source_names():
        return None
    return name, target


def find_program(name: str) -> str:
    """Return the full path of a program found on ``PATH``.

    The current folder is never searched (a program planted next to a log must not run), relative ``PATH`` entries are
    ignored, and on Windows only ``.exe`` and ``.com`` files count, because a batch file would start a command shell.

    Args:
        name: Program name without a folder.

    Returns:
        The full path.

    Raises:
        SourceError: If the program is not found.
    """
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        folder = Path(entry.strip('"'))
        if not entry or not folder.is_absolute():
            continue
        for suffix in _SUFFIXES:
            candidate = folder / (name + suffix)
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
    raise SourceError(f"{name} was not found on PATH", hint=f"install {name}, or save the log to a file first")


def _kill(process: subprocess.Popen[bytes]) -> None:
    try:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass


def _drain(stream: IO[bytes], kept: list[bytes]) -> None:
    """Read a stream to its end and keep only its first bytes."""
    size = 0
    while chunk := stream.read(_CHUNK):
        if size < _STDERR_KEEP:
            kept.append(chunk[: _STDERR_KEEP - size])
            size += len(kept[-1])


def _size_text(size: int) -> str:
    for unit, scale in (("GiB", 1 << 30), ("MiB", 1 << 20), ("KiB", 1 << 10)):
        if size >= scale:
            return f"{size / scale:g} {unit}"
    return f"{size} bytes"


def _message(raw: bytes) -> str:
    """Make the text of a program safe to show in an error: no control characters, one line, short."""
    text = " ".join(printable(raw.decode("utf-8", errors="replace")).split())
    return text[:_MESSAGE_CHARS] + ("..." if len(text) > _MESSAGE_CHARS else "")


def _run(argv: list[str], merge_stderr: bool, path: Path, timeout: float, max_bytes: int) -> None:
    """Run the program and write its output to ``path``; raise ``SourceError`` when it fails or is stopped."""
    label = Path(argv[0]).stem
    options: dict[str, object] = {}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
    else:
        options["start_new_session"] = True
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT if merge_stderr else subprocess.PIPE,
            bufsize=0,
            **options,  # type: ignore[call-overload]
        )
    except OSError as error:
        raise SourceError(f"cannot start {label}: {error.strerror or error}") from None
    assert process.stdout is not None
    stopped: list[str] = []

    def stop(reason: str) -> None:
        if not stopped:
            stopped.append(reason)
            _kill(process)

    timer = threading.Timer(timeout, stop, ("timeout",))
    timer.daemon = True
    timer.start()
    errors: list[bytes] = []
    reader = None
    if process.stderr is not None:
        reader = threading.Thread(target=_drain, args=(process.stderr, errors), daemon=True)
        reader.start()
    written = 0
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as out:
            while chunk := process.stdout.read(_CHUNK):
                written += len(chunk)
                if written > max_bytes:
                    stop("size")
                    break
                out.write(chunk)
        process.wait()
    finally:
        timer.cancel()
        if process.poll() is None:
            _kill(process)
        process.stdout.close()
        process.wait()
        if reader is not None:
            reader.join(timeout=5)
    _check_outcome(label, process.returncode, stopped, timeout, max_bytes, path, b"".join(errors))


def _check_outcome(
    label: str, code: int, stopped: list[str], timeout: float, max_bytes: int, path: Path, errors: bytes
) -> None:
    if stopped == ["timeout"]:
        raise SourceError(
            f"{label} did not finish in {timeout:g} s",
            hint="read less with --source-tail or --source-since, or raise --source-timeout",
        )
    if stopped == ["size"]:
        raise SourceError(
            f"the output of {label} is larger than {_size_text(max_bytes)}",
            hint="read less with --source-tail or --source-since, or raise --source-max-size",
        )
    if code != 0:
        if not errors:
            with open(path, "rb") as head:
                errors = head.read(_STDERR_KEEP)
        text = _message(errors)
        raise SourceError(f"{label} failed (exit code {code})" + (f": {text}" if text else ""))


@contextmanager
def fetch(
    source: str,
    *,
    tail: int | None = None,
    since: str | None = None,
    previous: bool = False,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> Iterator[Path]:
    """Read a log from a program of the user and give it as a temporary file.

    This runs the program ``docker``, ``kubectl`` or ``journalctl`` (or a source that a plugin adds) that is found on
    ``PATH``, without a shell and read-only; it never follows the log. The functions that analyze a log take paths
    only and never start a program; use this to turn a source into a path::

        with logfold.fetch("docker:web", tail=10_000) as path:
            result = logfold.analyze(path)

    The file is private to the user and is removed when the block ends, also on an error or an interrupt.

    Args:
        source: ``docker:NAME``, ``kubectl:NAMESPACE/POD[/CONTAINER]``, ``journalctl:UNIT``, or another registered
            source and its target.
        tail: Read only the last this many lines.
        since: Read only what is newer than this, as the program accepts it (``15m``, ``2026-10-14T10:00:00``).
        previous: Read the previous instance of the container (``kubectl`` only).
        timeout: Seconds before the program is stopped.
        max_bytes: Bytes of output before the program is stopped; more than that is an error, never a silent cut.

    Yields:
        The path of the temporary file.

    Raises:
        ConfigError: If ``source`` is not a registered source with a valid target, or a limit is not positive.
        SourceError: If the program is missing, fails, runs too long or prints too much.
    """
    parsed = split_source(source)
    if parsed is None:
        raise ConfigError(
            f"{source!r} is not a source",
            hint=f"a source looks like docker:web; known sources: {', '.join(source_names())}",
        )
    if timeout <= 0 or max_bytes < 1:
        raise ConfigError("timeout and max_bytes must be positive")
    chosen = get_source(parsed[0])
    if chosen.platforms and not sys.platform.startswith(chosen.platforms):
        raise SourceError(
            f"{chosen.name} is not available on {sys.platform}", hint="save the log to a file where it exists"
        )
    command = chosen.command(parsed[1], SourceOptions(tail, since, previous))
    program = find_program(command.argv[0])
    folder = Path(tempfile.mkdtemp(prefix="logfold-source-"))
    path = folder / "source.log"
    set_label(str(path), source)
    try:
        _run([program, *command.argv[1:]], command.merge_stderr, path, timeout, max_bytes)
        yield path
    finally:
        clear_label(str(path))
        shutil.rmtree(folder, ignore_errors=True)
