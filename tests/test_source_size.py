"""Project rule: a source file has at most 500 lines (CLAUDE.md, code style)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIMIT = 500
SOURCE_DIRS = ("python", "tests", "crates", "bench", "eval", "examples")
SKIPPED_PARTS = {"target", ".venv", "__pycache__", "node_modules", ".git"}


def source_files() -> list[Path]:
    found: list[Path] = []
    for name in SOURCE_DIRS:
        directory = ROOT / name
        if not directory.is_dir():
            continue
        for suffix in ("*.py", "*.rs"):
            found.extend(path for path in directory.rglob(suffix) if not SKIPPED_PARTS & set(path.parts))
    return sorted(found)


def test_no_source_file_exceeds_the_limit() -> None:
    files = source_files()
    assert files, "no source files found; the test is looking in the wrong place"
    too_long = {
        path.relative_to(ROOT).as_posix(): count
        for path in files
        if (count := len(path.read_text(encoding="utf-8").splitlines())) > LIMIT
    }
    assert not too_long, f"split these files by responsibility (limit {LIMIT} lines): {too_long}"
