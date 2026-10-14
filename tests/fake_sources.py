"""A source that runs a small Python script instead of ``docker``, so that the runner is tested without any service."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from logfold.ext import registry
from logfold.ext.sources import Command, SourceOptions

PYTHON = Path(sys.executable).name.removesuffix(".exe")

SCRIPT = r"""
import sys, time
mode = sys.argv[1]
if mode == "ok":
    for i in range(50):
        print(f"2026-10-14 10:00:{i % 60:02d} INFO request {i} served in {i * 7} ms")
elif mode == "both":
    print("2026-10-14 10:00:00 INFO to stdout")
    sys.stdout.flush()
    print("2026-10-14 10:00:01 WARN to stderr", file=sys.stderr)
elif mode == "fail":
    print("Error: no such thing \x1b[31mred", file=sys.stderr)
    sys.exit(3)
elif mode == "sleep":
    time.sleep(60)
elif mode == "big":
    sys.stdout.write(("x" * 1023 + "\n") * 5000)
elif mode == "args":
    print("2026-10-14 10:00:00 INFO " + " ".join(sys.argv[1:]))
"""


class FakeSource:
    """``fake:MODE`` runs the script above in the mode named by the target."""

    name = "fake"
    description = "a script that stands in for a program"
    platforms: tuple[str, ...] = ()

    def command(self, target: str, options: SourceOptions) -> Command:
        """Return the script command; ``both`` reads the error stream as part of the log."""
        return Command((PYTHON, "-c", SCRIPT, target), merge_stderr=target == "both")


@pytest.fixture
def fake_source(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Register ``fake:`` with the folder of Python on ``PATH``; return the folder that holds the temporary files."""
    monkeypatch.setenv("PATH", os.path.dirname(sys.executable) + os.pathsep + os.environ.get("PATH", ""))
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(temp))
    registry.load_plugins()
    registry.register_source(FakeSource())
    yield temp
    registry._sources.pop("fake", None)
