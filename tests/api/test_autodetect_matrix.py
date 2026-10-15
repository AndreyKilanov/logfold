"""The format auto-detection never picks a wrong format, whatever the head of the log looks like.

``bench/validate/autodetect.py`` runs the whole matrix (real programs, other projects' logs, Loghub); this is the slice
that runs in CI. For every format a Hypothesis strategy writes a damaged log (``tests/format_grammars.py``: cut lines, a
byte order mark, CR LF, a banner, bytes that are not UTF-8) and the detector must give one of the answers that are
allowed for that format: the format itself, a format that reads the same records (``ALLOWED``), or a refusal. A refusal
is never a failure: the user names the format. Picking another format is. A log with CR line endings only is one line
for every format, so it is left out (the sample has to have lines).
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from format_grammars import GRAMMARS, mutated_log
from logfold.errors import FormatDetectionError
from logfold.formats.auto import detect_format

pytestmark = requires_native

EXAMPLES = int(os.environ.get("LOGFOLD_FUZZ_EXAMPLES", "40"))
SETTINGS = settings(
    max_examples=EXAMPLES,
    deadline=timedelta(seconds=30),
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large],
)
ALLOWED: dict[str, set[str]] = {
    "nginx": {"nginx", "apache"},
    "apache": {"nginx", "apache"},
    "nginx-error": {"nginx-error"},
    "syslog": {"syslog"},
    "k8s": {"k8s"},
    "jsonl": {"jsonl"},
    "journald": {"journald"},
    "app": {"app"},
    "docker-json": {"docker-json", "jsonl"},
    "haproxy": {"syslog"},
    "log4j": {"app"},
}
"""The formats that ``-f auto`` may pick for a log of each format. A format that is not here may only be refused."""
LINE_FEED = chr(10).encode()
PROSE = "Loading configuration item {n} from the defaults of the service"


def picked(data: bytes) -> str | None:
    """Return the name of the format that ``auto`` picks for ``data``, or ``None`` when it refuses."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "detect.log"
        path.write_bytes(data)
        try:
            return detect_format([str(path)]).spec.name
        except FormatDetectionError:
            return None


@pytest.mark.parametrize("name", sorted(GRAMMARS))
def test_the_detector_never_picks_a_wrong_format(name: str) -> None:
    @SETTINGS
    @given(data=mutated_log(GRAMMARS[name], max_lines=60))
    def check(data: bytes) -> None:
        assume(data.count(LINE_FEED) >= 3)
        found = picked(data)
        assert found is None or found in ALLOWED.get(name, set()) | {"plain"}, found

    check()


@pytest.mark.parametrize("name", sorted(set(GRAMMARS) - {"plain"}))
def test_a_long_head_of_prose_is_refused_and_never_misread(name: str) -> None:
    prose = "\n".join(PROSE.format(n=n) for n in range(220)) + "\n"

    @SETTINGS
    @given(lines=st.lists(GRAMMARS[name], min_size=5, max_size=30))
    def check(lines: list[str]) -> None:
        assert picked((prose + "\n".join(lines) + "\n").encode()) is None

    check()


def docker_line(text: str, second: int) -> str:
    return json.dumps({"log": text, "stream": "stdout", "time": f"2026-10-06T12:00:{second:02d}.123456789Z"}) + chr(10)


def test_a_docker_log_is_not_read_as_plain_json_lines(tmp_path: Path) -> None:
    log = tmp_path / "docker.log"
    entries = [docker_line(f"user {n} logged in" + chr(10), n) for n in range(9)]
    entries.append(docker_line("a line of 16 KB cut ", 9))
    log.write_text("".join(entries), encoding="utf-8")
    assert detect_format([str(log)]).spec.name == "docker-json"


def test_entries_without_a_line_break_are_not_joined_into_one_record(tmp_path: Path) -> None:
    log = tmp_path / "stripped.log"
    log.write_text("".join(docker_line(f"message {n}", n) for n in range(5)), encoding="utf-8")
    assert detect_format([str(log)]).spec.name == "jsonl"
    assert logfold.analyze(log, format="auto").run.records == 5


def test_json_lines_with_a_log_key_but_no_docker_keys_stay_json_lines(tmp_path: Path) -> None:
    log = tmp_path / "service.log"
    log.write_text('{"log":"started","level":"info"}' + chr(10) + '{"log":"stopped","level":"warn"}' + chr(10))
    assert detect_format([str(log)]).spec.name == "jsonl"
