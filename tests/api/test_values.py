"""``analyze(values=True)``: the distributions of the values at the variable positions of frequent templates."""

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
PATHS = ["home", "login", "search", "cart"]
TOKEN = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vX7zA9cE1fG3hI5"


def access_lines(count: int) -> list[str]:
    lines = []
    for n in range(count):
        status = 404 if n % 10 == 0 else 200
        lines.append(f"GET /{PATHS[n % 4]} {status} {1 + n % 100}")
    lines.extend(f"worker w{n % 3} restarted after {10 + n % 7} seconds idle" for n in range(count // 20))
    return lines


@pytest.fixture
def access_log(tmp_path: Path) -> Path:
    return write(tmp_path / "access.log", access_lines(2000))


def analyzed(log: Path, **options: object) -> logfold.AnalysisResult:
    return logfold.analyze(str(log), format="plain", **options)  # type: ignore[arg-type]


def by_text(result: logfold.AnalysisResult, prefix: str) -> logfold.Template:
    return next(template for template in result.templates if template.text.startswith(prefix))


def test_nothing_is_counted_unless_asked_for(access_log: Path) -> None:
    result = analyzed(access_log)
    assert all(template.values is None for template in result.templates)


def test_the_values_of_the_positions_are_exact_and_the_numbers_have_percentiles(access_log: Path) -> None:
    template = by_text(analyzed(access_log, values=True), "GET")
    assert template.values is not None
    path, status, millis = template.values
    assert (path.position, path.name, path.count, path.distinct, path.capped) == (1, "*", 2000, 4, False)
    assert {count for _, count in path.top} == {500}
    assert path.numeric is None
    assert status.top == (("200", 1800), ("404", 200))
    assert millis.numeric is not None
    assert (millis.numeric.count, millis.numeric.min, millis.numeric.max) == (2000, 1.0, 100.0)
    assert millis.numeric.p50 == pytest.approx(50, rel=0.03)
    assert millis.numeric.p99 == pytest.approx(99, rel=0.03)
    assert template.count == 2000


def test_only_the_most_frequent_templates_are_tracked(access_log: Path) -> None:
    result = analyzed(access_log, values=True, value_templates=1)
    assert [template.text for template in result.templates if template.values is not None] == ["GET <*> <NUM> <NUM>"]
    with pytest.raises(ConfigError, match="value_templates"):
        analyzed(access_log, values=True, value_templates=0)


def test_the_counts_of_the_templates_are_those_of_the_second_pass(access_log: Path) -> None:
    result = analyzed(access_log, values=True)
    assert sum(template.count for template in result.templates) == result.run.records


def test_the_examples_mode_decides_how_the_values_are_shown(access_log: Path) -> None:
    raw = by_text(analyzed(access_log, values=True), "GET").values
    masked = by_text(analyzed(access_log, values=True, examples="masked"), "GET").values
    none = by_text(analyzed(access_log, values=True, examples="none"), "GET").values
    assert raw is not None
    assert masked is not None
    assert none is not None
    assert raw[1].top[0] == ("200", 1800)
    assert masked[1].top == (("<NUM>", 2000),)
    assert masked[1].count == raw[1].count
    assert none[1].top == ()
    assert none[2].numeric == raw[2].numeric


def test_a_value_that_a_mask_set_hides_is_never_listed(tmp_path: Path) -> None:
    lines = [f"call {n} used key {TOKEN} for {['north', 'south'][n % 2]}" for n in range(300)]
    log = write(tmp_path / "keys.log", lines)
    result = analyzed(log, values=True, masks=["secrets"])
    template = by_text(result, "call")
    assert "<KEY>" in template.text
    assert template.values is not None
    assert [item.name for item in template.values] == ["num", "*"]
    assert TOKEN not in json.dumps([item.top for item in template.values])
    payload = json.loads(result.to_json())
    shown = next(item for item in payload["templates"] if item["text"].startswith("call"))
    assert TOKEN not in json.dumps(shown["values"])


def validator() -> jsonschema.Draft202012Validator:
    resources = [
        (path.name, Resource.from_contents(json.loads(path.read_text(encoding="utf-8"))))
        for path in SCHEMA_DIR.glob("*.schema.json")
    ]
    schema = json.loads((SCHEMA_DIR / "analysis-v1.schema.json").read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=Registry().with_resources(resources))


def test_the_json_report_has_the_values_and_matches_the_schema(access_log: Path, tmp_path: Path) -> None:
    result = analyzed(access_log, values=True)
    payload = json.loads(result.to_json())
    validator().validate(payload)
    tracked = next(item for item in payload["templates"] if item["text"].startswith("GET"))
    assert tracked["values"][1]["top"][0] == {"value": "200", "count": 1800}
    assert tracked["values"][2]["numeric"]["max"] == 100.0
    plain = json.loads(analyzed(access_log).to_json())
    assert all("values" not in item for item in plain["templates"])
    validator().validate(plain)


def test_a_saved_report_keeps_the_values(access_log: Path, tmp_path: Path) -> None:
    result = analyzed(access_log, values=True)
    saved = tmp_path / "result.json"
    result.to_json(saved)
    assert logfold.load_analysis(saved).templates == result.templates


def test_the_text_and_html_reports_show_the_values(tmp_path: Path) -> None:
    lines = [f"GET /<script>alert({n % 3})</script> 200 {n % 50}" for n in range(300)]
    result = analyzed(write(tmp_path / "hostile.log", lines), values=True)
    text = result.render("text")
    assert "numbers (" in text
    assert "x" in text
    html = result.to_html()
    assert "<summary>values</summary>" in html
    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


def test_the_same_values_for_one_and_for_many_threads(access_log: Path) -> None:
    options = {"values": True, "strategy": "chunked", "chunk_bytes": 4096}
    one = analyzed(access_log, threads=1, **options)
    four = analyzed(access_log, threads=4, **options)
    assert [t.values for t in one.templates] == [t.values for t in four.templates]


def test_values_work_with_a_saved_state(access_log: Path, tmp_path: Path) -> None:
    result = analyzed(access_log, values=True, save_state=tmp_path / "model.json")
    again = analyzed(access_log, values=True, load_state=tmp_path / "model.json", strategy="sequential")
    assert by_text(again, "GET").values == by_text(result, "GET").values
