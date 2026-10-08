"""Write a pair of logs for checking the pipeline reporters with the real tools that read them.

The second log holds new alarming templates whose text is hostile to every output format: markup, a CDATA end marker,
label-value metacharacters, control characters, astral characters, a very long line. Nothing else is needed: the reporters
are tried on the diff of the two logs.

Usage: python bench/validate/make_samples.py DIRECTORY
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

HOSTILE = (
    ("ERROR", 'payload <script>alert("x")</script> & more'),
    ("ERROR", "cdata ]]> end marker and ]]&gt; confusion"),
    ("ERROR", 'quote " backslash \\ and label{a="b"} injection'),
    ("FATAL", "control \x01\x02 chars, snowman ☃ and a star \U0001f4a5"),
    ("WARN", "very long " + "x" * 5000),
    ("ERROR", "percent %s %d {} {{}} $(whoami) `id`"),
    ("ERROR", "tab\tinside and a trailing backslash \\"),
)


def _line(index: int, level: str, message: str) -> str:
    return f"2026-10-08T10:{index // 60 % 60:02d}:{index % 60:02d}Z {level} {message}"


def make_samples(directory: Path) -> tuple[Path, Path]:
    """Write ``before.log`` and ``after.log`` into ``directory`` and return their paths."""
    rng = random.Random(7)
    before, after = [], []
    for i in range(400):
        before.append(_line(i, "INFO", f"user {rng.randrange(1000)} logged in from 10.0.0.{rng.randrange(255)}"))
        after.append(_line(i, "INFO", f"user {rng.randrange(1000)} logged in from 10.0.0.{rng.randrange(255)}"))
    before += [_line(500 + i, "WARN", f"disk {rng.randrange(60, 99)}% full on /dev/sda{i % 3}") for i in range(20)]
    for i, (level, text) in enumerate(HOSTILE * 5):
        after.append(_line(600 + i, level, f"{text} #{i}"))
    after += [_line(700 + i, "ERROR", f"db timeout after {rng.randrange(10, 60)}s on shard {i % 4}") for i in range(30)]
    directory.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, lines in (("before.log", before), ("after.log", after)):
        path = directory / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        paths.append(path)
    return paths[0], paths[1]


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    first, second = make_samples(Path(sys.argv[1]))
    print(first, second)
