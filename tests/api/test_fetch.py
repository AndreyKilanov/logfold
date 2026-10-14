"""``logfold.fetch``: running a program of the user safely, with the output in a private temporary file."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from fake_sources import PYTHON
from logfold.api.fetch import find_program, split_source
from logfold.errors import ConfigError, SourceError
from logfold.ext import registry
from logfold.ext.sources import Command, SourceOptions


def _left(temp: Path) -> list[Path]:
    return list(temp.glob("logfold-source-*"))


def _register(name: str, command: Command | None, platforms: tuple[str, ...] = ()) -> type:
    class Plugin:
        description = "a source of a test"

        def command(self, target: str, options: SourceOptions) -> Command:
            if command is None:
                raise AssertionError("must not be called")
            return command

    Plugin.name = name  # type: ignore[attr-defined]
    Plugin.platforms = platforms  # type: ignore[attr-defined]
    registry.register_source(Plugin())  # type: ignore[arg-type]
    return Plugin


@pytest.fixture
def cleanup() -> object:
    yield
    for name in ("missing", "elsewhere", "reader"):
        registry._sources.pop(name, None)


def test_the_output_is_a_file_that_goes_away_with_the_block(fake_source: Path) -> None:
    with logfold.fetch("fake:ok") as path:
        assert len(path.read_text().splitlines()) == 50
        assert len(_left(fake_source)) == 1
    assert _left(fake_source) == []


@pytest.mark.skipif(sys.platform == "win32", reason="permission bits are checked on POSIX only")
def test_the_file_and_its_folder_are_private(fake_source: Path) -> None:
    with logfold.fetch("fake:ok") as path:
        assert path.stat().st_mode & 0o077 == 0
        assert path.parent.stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("error", [RuntimeError("boom"), KeyboardInterrupt()])
def test_the_file_goes_away_when_the_block_fails_or_is_interrupted(fake_source: Path, error: BaseException) -> None:
    with pytest.raises(type(error)), logfold.fetch("fake:ok"):
        raise error
    assert _left(fake_source) == []


@requires_native
def test_a_result_names_the_source_and_not_the_temporary_file(fake_source: Path) -> None:
    with logfold.fetch("fake:ok") as path:
        result = logfold.analyze(path, format="app")
    assert result.run.name == "fake:ok"
    assert result.run.records == 50


def test_the_error_stream_is_part_of_the_log_when_the_source_says_so(fake_source: Path) -> None:
    with logfold.fetch("fake:both") as path:
        text = path.read_text()
    assert "to stdout" in text
    assert "to stderr" in text


def test_a_failing_program_is_an_error_with_its_message_made_printable(fake_source: Path) -> None:
    with pytest.raises(SourceError) as caught, logfold.fetch("fake:fail"):
        pass
    message = str(caught.value)
    assert "exit code 3" in message
    assert "no such thing" in message
    assert "\x1b" not in message
    assert "\\x1b" in message
    assert _left(fake_source) == []


def test_a_program_that_runs_too_long_is_stopped(fake_source: Path) -> None:
    started = time.monotonic()
    with pytest.raises(SourceError, match="did not finish in 1 s") as caught, logfold.fetch("fake:sleep", timeout=1):
        pass
    assert time.monotonic() - started < 30
    assert "--source-timeout" in (caught.value.hint or "")
    assert _left(fake_source) == []


def test_output_over_the_limit_is_an_error_and_never_a_cut(fake_source: Path) -> None:
    with pytest.raises(SourceError, match="larger than 100 KiB") as caught, logfold.fetch("fake:big", max_bytes=102400):
        pass
    assert "--source-tail" in (caught.value.hint or "")
    assert _left(fake_source) == []


def test_output_within_the_limit_is_read_whole(fake_source: Path) -> None:
    with logfold.fetch("fake:big", max_bytes=1 << 30) as path:
        assert len(path.read_bytes().splitlines()) == 5000


def test_a_program_that_is_not_installed_is_an_error_with_a_hint(fake_source: Path, cleanup: object) -> None:
    _register("missing", Command(("logfold-no-such-program", "x")))
    with pytest.raises(SourceError, match="logfold-no-such-program was not found on PATH") as caught:
        logfold.fetch("missing:x").__enter__()
    assert "save the log to a file" in (caught.value.hint or "")
    assert _left(fake_source) == []


def test_a_program_planted_in_the_current_folder_does_not_run(
    fake_source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    planted = tmp_path / "work"
    planted.mkdir()
    program = planted / ("logfold-planted.exe" if sys.platform == "win32" else "logfold-planted")
    program.write_bytes(b"#!/bin/sh\ntouch ran\n")
    program.chmod(0o755)
    monkeypatch.chdir(planted)
    monkeypatch.setenv("PATH", os.pathsep.join(["", ".", os.environ["PATH"]]))
    with pytest.raises(SourceError, match="was not found on PATH"):
        find_program("logfold-planted")
    assert not (planted / "ran").exists()


@pytest.mark.skipif(sys.platform == "win32", reason="the Windows case is the next test")
def test_a_program_is_found_by_its_full_path_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tool = tmp_path / "tool"
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert find_program("tool") == str(tool)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_on_windows_a_batch_file_is_not_a_program(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "tool.bat").write_text("@echo off\n")
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(SourceError, match="was not found"):
        find_program("tool")


def test_a_source_that_does_not_work_here_is_refused_before_anything_runs(fake_source: Path, cleanup: object) -> None:
    _register("elsewhere", None, platforms=("no-such-platform",))
    with pytest.raises(SourceError, match="is not available on"):
        logfold.fetch("elsewhere:x").__enter__()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("docker:web", ("docker", "web")),
        ("kubectl:prod/web-7d9/app", ("kubectl", "prod/web-7d9/app")),
        ("journalctl:nginx.service", ("journalctl", "nginx.service")),
        ("./docker:web", None),
        ("docker:", None),
        ("web.log", None),
        ("-", None),
        ("C:\\logs\\a.log", None),
        ("d:/logs/a.log", None),
        ("unknown:web", None),
    ],
)
def test_only_a_registered_name_before_a_colon_makes_a_source(text: str, expected: tuple[str, str] | None) -> None:
    assert split_source(text) == expected


@pytest.mark.parametrize("text", ["web.log", "unknown:x", "./docker:web"])
def test_a_text_that_is_not_a_source_is_refused(text: str) -> None:
    with pytest.raises(ConfigError, match="is not a source") as caught:
        logfold.fetch(text).__enter__()
    assert "docker" in (caught.value.hint or "")


@pytest.mark.parametrize(("timeout", "max_bytes"), [(0, 10), (-1, 10), (5, 0)])
def test_limits_must_be_positive(fake_source: Path, timeout: float, max_bytes: int) -> None:
    with pytest.raises(ConfigError, match="must be positive"):
        logfold.fetch("fake:ok", timeout=timeout, max_bytes=max_bytes).__enter__()
    assert _left(fake_source) == []


def test_the_program_gets_no_standard_input(fake_source: Path, cleanup: object) -> None:
    _register("reader", Command((PYTHON, "-c", "import sys; print(repr(sys.stdin.read()))")))
    with logfold.fetch("reader:x") as path:
        assert path.read_text().strip() == "''"
