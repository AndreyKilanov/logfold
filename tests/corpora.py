"""Deterministic synthetic log corpora used by the tests."""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from pathlib import Path

HOSTS = ("alpha", "beta", "gamma", "delta")
USERS = ("alice", "bob", "carol", "dave", "erin", "frank")


def _iso(i: int) -> str:
    return f"2026-10-04T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}Z"


def app_lines(count: int, seed: int = 1) -> list[str]:
    """Application log lines with ISO timestamps and levels."""
    rng = random.Random(seed)
    lines = []
    for i in range(count):
        kind = rng.randrange(7)
        ts = _iso(i)
        if kind == 0:
            lines.append(
                f"{ts} INFO user {rng.choice(USERS)} logged in from 10.0.{rng.randrange(9)}.{rng.randrange(1, 250)}"
            )
        elif kind == 1:
            lines.append(f"{ts} WARN disk usage {rng.randrange(50, 99)}% on /dev/sda{rng.randrange(1, 4)}")
        elif kind == 2:
            lines.append(
                f"{ts} ERROR request {rng.randrange(1, 99999)} failed with status {rng.choice((500, 502, 503))}"
            )
        elif kind == 3:
            lines.append(f"{ts} INFO cache miss for key k{rng.randrange(1000)}")
        elif kind == 4:
            lines.append(f"{ts} DEBUG heartbeat from {rng.choice(HOSTS)}")
        elif kind == 5:
            lines.append(f"{ts} INFO job {rng.randrange(1000)} finished in {rng.random() * 10:.2f}s")
        else:
            lines.append(f"{ts} ERROR unexpected exception in handler {rng.choice(HOSTS)}")
    return lines


def multiline_lines(count: int, seed: int = 2) -> list[str]:
    """Application log with indented stack traces."""
    rng = random.Random(seed)
    lines = []
    for i, base in enumerate(app_lines(count, seed)):
        lines.append(base)
        if "exception" in base:
            lines.append(f'  File "service.py", line {rng.randrange(1, 90)}, in handle')
            lines.append("    raise RuntimeError('boom')")
        if i % 17 == 0:
            lines.append("")
    return lines


def nginx_lines(count: int, seed: int = 3) -> list[str]:
    """Combined access log lines."""
    rng = random.Random(seed)
    lines = []
    for i in range(count):
        method = rng.choice(("GET", "GET", "POST", "PUT"))
        path = rng.choice(("/", "/api/items", f"/api/items/{rng.randrange(1000)}", "/static/app.js", "/login"))
        status = rng.choice((200, 200, 200, 301, 404, 500))
        ts = f"04/Oct/2026:{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d} +0300"
        lines.append(
            f'10.1.{rng.randrange(5)}.{rng.randrange(1, 250)} - - [{ts}] "{method} {path} HTTP/1.1" {status} '
            f'{rng.randrange(100, 9000)} "-" "curl/8.0"'
        )
    return lines


def syslog_lines(count: int, seed: int = 4) -> list[str]:
    """Classic syslog lines with padded days."""
    rng = random.Random(seed)
    lines = []
    for i in range(count):
        day = 1 + (i // 5000) % 28
        stamp = f"Oct {day:2d} {(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}"
        service = rng.choice(("sshd", "cron", "kernel"))
        state = rng.choice(("opened", "closed"))
        lines.append(f"{stamp} host1 {service}[{rng.randrange(100, 999)}]: session {state} for {rng.choice(USERS)}")
    return lines


def json_lines(count: int, seed: int = 5) -> list[str]:
    """JSON lines with several timestamp and level encodings."""
    rng = random.Random(seed)
    lines = []
    for i in range(count):
        kind = i % 4
        if kind == 0:
            row = {"ts": _iso(i), "level": "info", "msg": f"user {rng.choice(USERS)} signed in"}
        elif kind == 1:
            row = {"time": 1_790_000_000 + i, "severity": "WARNING", "message": f"queue depth {rng.randrange(500)}"}
        elif kind == 2:
            row = {
                "timestamp": f"2026-10-04 12:00:{i % 60:02d}.{rng.randrange(1000):03d}+02:00",
                "lvl": "err",
                "log": "payment failed",
            }
        else:
            row = {"msg": f"retry {rng.randrange(5)} for {rng.choice(HOSTS)}", "extra": {"nested": [1, 2]}}
        lines.append(json.dumps(row))
    lines.insert(3, "this is not json")
    lines.insert(7, json.dumps([1, 2, 3]))
    lines.insert(9, json.dumps({"no_message": True}))
    return lines


def journald_lines(count: int, seed: int = 6) -> list[str]:
    """journalctl -o json lines."""
    rng = random.Random(seed)
    lines = []
    for i in range(count):
        row = {
            "__REALTIME_TIMESTAMP": str(1_790_000_000_000_000 + i * 1000),
            "PRIORITY": str(rng.choice((3, 4, 6, 6, 7))),
            "MESSAGE": f"Started session {rng.randrange(100)} of user {rng.choice(USERS)}.",
        }
        lines.append(json.dumps(row))
    return lines


def unicode_lines(count: int, seed: int = 7) -> list[str]:
    """Plain lines with non-ASCII text and odd whitespace."""
    rng = random.Random(seed)
    words = ("привет", "мир", "café", "naïve", "日本語", "emoji🙂", "plain", "тест")
    lines = []
    for _ in range(count):
        n = rng.randrange(1, 7)
        lines.append(
            " ".join(rng.choice(words) + (str(rng.randrange(50)) if rng.random() < 0.3 else "") for _ in range(n))
        )
    return lines


def noisy_lines(count: int, seed: int = 8) -> list[str]:
    """Plain lines with many distinct shapes, to exercise the tree and overflow."""
    rng = random.Random(seed)
    vocab = [f"w{i}" for i in range(40)] + ["error", "ok", "start", "stop", "<*>", "x=1", "a/b/c", "0xFF"]
    lines = []
    for _ in range(count):
        n = rng.randrange(0, 9)
        lines.append(" ".join(rng.choice(vocab) for _ in range(n)))
    return lines


CORPORA: dict[str, tuple[Callable[[int], list[str]], str, bool]] = {
    "app": (app_lines, "app", False),
    "multiline": (multiline_lines, "app", True),
    "nginx": (nginx_lines, "nginx", False),
    "syslog": (syslog_lines, "syslog", False),
    "jsonl": (json_lines, "jsonl", False),
    "journald": (journald_lines, "journald", False),
    "unicode": (unicode_lines, "plain", False),
    "noisy": (noisy_lines, "plain", False),
}


def write(path: Path, lines: list[str], *, crlf: bool = False, final_newline: bool = True) -> Path:
    """Write ``lines`` to ``path`` with the requested line endings."""
    eol = "\r\n" if crlf else "\n"
    text = eol.join(lines) + (eol if final_newline else "")
    path.write_bytes(text.encode("utf-8"))
    return path
