"""``diff(new_values=True)``: the values of a variable position that only one of the two runs has."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

import logfold
from conftest import requires_native
from corpora import write
from logfold import ConfigError

pytestmark = requires_native

SCHEMA_DIR = Path(__file__).parents[2] / "docs" / "schema"
TOKEN = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vX7zA9cE1fG3hI5"


def catalog(ids: range, level: str = "INFO", hour: int = 10) -> list[str]:
    lines = []
    for item in ids:
        for _ in range(item % 3 + 1):
            lines.append(f"2026-10-15 {hour:02d}:{item % 60:02d}:00 {level} added item {item} to the catalog")
        lines.append(f"2026-10-15 {hour:02d}:{item % 60:02d}:01 INFO health check ok")
    return lines


@pytest.fixture
def pair(tmp_path: Path) -> tuple[Path, Path]:
    return write(tmp_path / "a.log", catalog(range(1, 51))), write(tmp_path / "b.log", catalog(range(31, 81)))


def compared(pair: tuple[Path, Path], **options: object) -> logfold.DiffResult:
    return logfold.diff(str(pair[0]), str(pair[1]), new_values=True, **options)  # type: ignore[arg-type]


def test_nothing_is_compared_unless_asked_for(pair: tuple[Path, Path]) -> None:
    assert logfold.diff(str(pair[0]), str(pair[1])).value_changes is None


def test_the_new_and_gone_values_of_a_shared_template_are_listed(pair: tuple[Path, Path]) -> None:
    result = compared(pair)
    assert result.value_changes is not None
    assert [item.text for item in result.value_changes] == ["added item <NUM> to the catalog"]
    change = result.value_changes[0].changes[0]
    assert (change.position, change.name) == (2, "num")
    assert (change.new_distinct, change.gone_distinct, change.shared_distinct) == (30, 30, 20)
    assert (change.before_distinct, change.after_distinct, change.capped) == (50, 50, False)
    assert [value for value, _ in change.new[:3]] == ["53", "56", "59"]
    assert all(count == 3 for _, count in change.new)
    assert len(change.new) == len(change.gone) == 10
    assert result.value_changes[0].level == "INFO"


def test_the_gates_and_the_other_lists_do_not_depend_on_the_values(pair: tuple[Path, Path]) -> None:
    plain = logfold.diff(str(pair[0]), str(pair[1]))
    asked = compared(pair)
    assert asked.new_templates == plain.new_templates
    assert asked.changed == plain.changed
    assert asked.disappeared == plain.disappeared


def test_examples_decide_how_the_values_are_shown(pair: tuple[Path, Path]) -> None:
    masked = compared(pair, examples="masked").value_changes
    none = compared(pair, examples="none").value_changes
    assert masked is not None
    assert none is not None
    assert masked[0].changes[0].new[0] == ("<NUM>", 30)
    assert none[0].changes[0].new == ()
    assert none[0].changes[0].new_distinct == 30


def test_a_template_of_one_run_is_not_compared(tmp_path: Path) -> None:
    first = write(tmp_path / "a.log", catalog(range(1, 6)))
    second = write(tmp_path / "b.log", [*catalog(range(1, 6)), "2026-10-15 10:59:00 INFO cache warmed in 12 ms"])
    result = logfold.diff(str(first), str(second), new_values=True)
    assert result.value_changes == ()


def test_the_level_filter_follows_the_level_of_the_template(tmp_path: Path) -> None:
    first = write(tmp_path / "a.log", [*catalog(range(1, 20)), *catalog(range(100, 120), "ERROR")])
    second = write(tmp_path / "b.log", [*catalog(range(10, 30)), *catalog(range(110, 130), "ERROR")])
    result = logfold.diff(str(first), str(second), new_values=True, min_count=1000)
    assert result.value_changes is not None
    kept = result.filter(min_level="ERROR").value_changes
    assert kept is not None
    assert [item.level for item in kept] == ["ERROR"]
    assert len(result.value_changes) == 1


def test_one_log_split_in_time_can_be_compared(tmp_path: Path) -> None:
    log = write(tmp_path / "app.log", [*catalog(range(1, 30), hour=10), *catalog(range(20, 50), hour=14)])
    result = logfold.diff(str(log), split_at="2026-10-15T12:00", new_values=True)
    assert result.value_changes is not None
    assert result.value_changes[0].changes[0].new_distinct == 20
    assert result.value_changes[0].changes[0].gone_distinct == 19


def test_only_the_asked_number_of_templates_is_compared(tmp_path: Path) -> None:
    lines = catalog(range(1, 30)) + [f"2026-10-15 11:00:00 INFO job {n} of batch {n % 5} done" for n in range(40)]
    first = write(tmp_path / "a.log", lines)
    second = write(tmp_path / "b.log", [*lines, "2026-10-15 11:30:00 INFO job 900 of batch 9 done"])
    both = logfold.diff(str(first), str(second), new_values=True, value_templates=5)
    one = logfold.diff(str(first), str(second), new_values=True, value_templates=1)
    assert both.value_changes is not None
    assert one.value_changes is not None
    assert len(one.value_changes) <= 1 < len(both.value_changes) + 1


def test_the_options_that_cannot_work_are_refused(pair: tuple[Path, Path]) -> None:
    first = logfold.analyze(str(pair[0]))
    second = logfold.analyze(str(pair[1]))
    with pytest.raises(ConfigError, match="saved analysis result"):
        logfold.diff(first, second, new_values=True)
    with pytest.raises(ConfigError, match="baselines"):
        logfold.diff(str(pair[0]), str(pair[1]), new_values=True, baselines=[str(pair[0])])
    with pytest.raises(ConfigError, match="recount"):
        compared(pair, recount=False)
    with pytest.raises(ConfigError, match="at least 1"):
        compared(pair, value_templates=0)


def test_the_values_of_a_hidden_mask_set_are_never_compared(tmp_path: Path) -> None:
    first = write(tmp_path / "a.log", [f"2026-10-15 10:00:00 INFO token {TOKEN[:-3]}{n:03d} used" for n in range(40)])
    second = write(
        tmp_path / "b.log", [f"2026-10-15 10:00:00 INFO token {TOKEN[:-3]}{n:03d} used" for n in range(20, 60)]
    )
    result = logfold.diff(str(first), str(second), new_values=True, masks=["secrets"])
    assert result.value_changes == ()
    assert TOKEN[:10] not in json.dumps(result.render("json"))


def test_the_json_report_matches_the_schema(pair: tuple[Path, Path]) -> None:
    resources = [
        (path.name, Resource.from_contents(json.loads(path.read_text(encoding="utf-8"))))
        for path in SCHEMA_DIR.glob("*.schema.json")
    ]
    schema = json.loads((SCHEMA_DIR / "diff-v1.schema.json").read_text(encoding="utf-8"))
    validator = jsonschema.Draft202012Validator(schema, registry=Registry().with_resources(resources))
    document = json.loads(compared(pair).render("json"))
    validator.validate(document)
    assert document["value_changes"][0]["positions"][0]["new"][0] == {"value": "53", "count": 3}
    without = json.loads(logfold.diff(str(pair[0]), str(pair[1])).render("json"))
    validator.validate(without)
    assert "value_changes" not in without


def test_the_reports_show_the_values_and_escape_them(tmp_path: Path) -> None:
    hostile = "<script>alert(1)</script>"
    first = write(tmp_path / "a.log", [f"2026-10-15 10:00:00 INFO user {name} logged in" for name in ("ann", "bob")])
    second = write(
        tmp_path / "b.log",
        [f"2026-10-15 10:00:00 INFO user {name} logged in" for name in ("bob", hostile, "\x1b[31mred")],
    )
    result = logfold.diff(str(first), str(second), new_values=True)
    assert result.value_changes is not None
    text = result.render("text")
    assert "Values that differ (1 templates)" in text
    assert "ann" in text
    assert "\x1b" not in text
    html = result.render("html")
    assert "Values that differ" in html
    assert hostile not in html
    assert "&lt;script&gt;" in html
    markdown = result.render("markdown")
    assert "## Values that differ" in markdown
    assert "\x1b" not in markdown
    assert "Values that differ" not in logfold.diff(str(first), str(second)).render("text")
