"""README.md is the description on PyPI, which cannot resolve relative links, so every link there must be absolute."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
README = ROOT / "README.md"
REPOSITORY = "https://github.com/AndreyKilanov/logfold/"
RAW = "https://raw.githubusercontent.com/AndreyKilanov/logfold/main/"
FENCE = re.compile(r"```.*?```", re.DOTALL)


def targets(text: str) -> list[str]:
    text = FENCE.sub("", text)
    found = re.findall(r'(?:href|src)="([^"]+)"', text)
    found += re.findall(r"\]\(([^)\s]+)\)", text)
    return found


def test_every_link_and_image_of_the_readme_is_absolute() -> None:
    relative = [
        t for t in targets(README.read_text(encoding="utf-8")) if not t.startswith(("https://", "http://", "#"))
    ]
    assert not relative, f"PyPI cannot resolve these, use absolute URLs: {relative}"


def test_links_into_the_repository_point_at_files_that_exist() -> None:
    missing = []
    for url in targets(README.read_text(encoding="utf-8")):
        for prefix in (REPOSITORY + "blob/main/", REPOSITORY + "tree/main/", RAW):
            if url.startswith(prefix):
                path = url[len(prefix) :].split("#")[0]
                if not (ROOT / path).exists():
                    missing.append(path)
    assert not missing, f"README.md links to files that are not in the repository: {missing}"


def test_the_russian_readme_has_the_same_sections() -> None:
    russian = ROOT / "README.ru.md"
    english = README.read_text(encoding="utf-8")
    other = russian.read_text(encoding="utf-8")
    headings = lambda text: [line for line in FENCE.sub("", text).splitlines() if line.startswith("#")]  # noqa: E731
    assert len(headings(english)) == len(headings(other))
    assert len(re.findall(r"^\|---", english, re.M)) == len(re.findall(r"^\|---", other, re.M))
