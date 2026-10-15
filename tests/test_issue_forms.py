"""The issue forms in ``.github/ISSUE_TEMPLATE`` are valid and the format form is reachable from the docs."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
FORMS = ROOT / ".github" / "ISSUE_TEMPLATE"
LABELS = {entry["name"] for entry in yaml.safe_load((ROOT / ".github" / "labels.yml").read_text(encoding="utf-8"))}
FORM_LINK = "https://github.com/AndreyKilanov/logfold/issues/new?template=format_problem.yml"


def forms() -> list[Path]:
    return sorted(path for path in FORMS.glob("*.yml") if path.name != "config.yml")


@pytest.mark.parametrize("path", forms(), ids=lambda path: path.name)
def test_a_form_has_known_labels_and_unique_fields(path: Path) -> None:
    form = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert form["name"]
    assert form["description"]
    assert set(form["labels"]) <= LABELS
    ids = [item["id"] for item in form["body"] if "id" in item]
    assert len(ids) == len(set(ids))
    assert any(item["validations"]["required"] for item in form["body"] if "validations" in item)


def test_the_format_form_asks_for_what_a_format_report_needs() -> None:
    form = yaml.safe_load((FORMS / "format_problem.yml").read_text(encoding="utf-8"))
    required = {item["id"] for item in form["body"] if item.get("validations", {}).get("required")}
    assert {"program", "format", "lines", "expected", "versions"} <= required
    assert {"type:bug", "area:formats"} <= set(form["labels"])


@pytest.mark.parametrize("name", ["README.md", "README.ru.md"])
def test_the_readmes_link_to_the_format_form(name: str) -> None:
    assert FORM_LINK in (ROOT / name).read_text(encoding="utf-8")
