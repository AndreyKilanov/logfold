"""Relative links in ``docs/*.md`` point at files and headings that exist."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DOCS = sorted((ROOT / "docs").glob("*.md"))
FENCE = re.compile(r"```.*?```", re.DOTALL)
LINK = re.compile(r"\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    """The anchor GitHub makes of a heading."""
    text = heading.strip().lower().replace("`", "")
    return re.sub(r"[^\w\- ]", "", text).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    text = FENCE.sub("", path.read_text(encoding="utf-8"))
    return {slug(line.lstrip("#")) for line in text.splitlines() if line.startswith("#")}


def broken(path: Path) -> list[str]:
    problems = []
    for target in LINK.findall(FENCE.sub("", path.read_text(encoding="utf-8"))):
        if target.startswith(("https://", "http://", "mailto:")):
            continue
        name, _, anchor = target.partition("#")
        linked = (path.parent / name).resolve() if name else path
        if not linked.exists():
            problems.append(f"{target}: no such file")
        elif anchor and linked.suffix == ".md" and anchor not in anchors(linked):
            problems.append(f"{target}: no such heading")
    return problems


@pytest.mark.parametrize("path", DOCS, ids=lambda path: path.name)
def test_the_links_of_a_page_resolve(path: Path) -> None:
    assert not broken(path)
