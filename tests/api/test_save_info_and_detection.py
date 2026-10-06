from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path

import pytest

import logfold
from logfold.engines import native
from logfold.errors import ConfigError, UnknownSuffixError
from logfold.ext import registry


@pytest.fixture(scope="module")
def analysis(corpus_dir: Path) -> logfold.AnalysisResult:
    return logfold.analyze(str(corpus_dir / "app.log"), format="app")


@pytest.fixture(scope="module")
def comparison(corpus_dir: Path) -> logfold.DiffResult:
    return logfold.diff(str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app")


@pytest.mark.parametrize(
    ("suffix", "reporter", "marker"),
    [
        (".html", "html", "<html"),
        (".htm", "html", "<html"),
        (".json", "json", '"kind"'),
        (".txt", "text", "templates"),
        (".md", "markdown", "| count |"),
        (".csv", "csv", "count,level"),
        (".HTML", "html", "<html"),
    ],
)
def test_save_picks_the_reporter_from_the_suffix(
    analysis: logfold.AnalysisResult, tmp_path: Path, suffix: str, reporter: str, marker: str
) -> None:
    target = tmp_path / f"report{suffix}"
    text = analysis.save(target)
    assert target.read_text(encoding="utf-8") == text
    assert text == analysis.render(reporter)
    assert marker in text


def test_save_takes_an_explicit_reporter_over_the_suffix(analysis: logfold.AnalysisResult, tmp_path: Path) -> None:
    target = tmp_path / "templates.txt"
    analysis.save(target, "csv")
    assert target.read_text(encoding="utf-8").startswith("count,level")
    analysis.save(tmp_path / "no-suffix", "markdown")
    assert (tmp_path / "no-suffix").read_text(encoding="utf-8").startswith("# ")


def test_save_passes_reporter_options(analysis: logfold.AnalysisResult, tmp_path: Path) -> None:
    text = analysis.save(tmp_path / "short.txt", top=2)
    assert text == analysis.render("text", top=2)
    assert "more templates" in text


def test_a_diff_saves_the_same_way(comparison: logfold.DiffResult, tmp_path: Path) -> None:
    text = comparison.save(tmp_path / "diff.md")
    assert text == comparison.render("markdown")
    assert json.loads(comparison.save(tmp_path / "diff.json"))["kind"] == "diff"


def test_an_unknown_suffix_is_an_error_and_writes_nothing(analysis: logfold.AnalysisResult, tmp_path: Path) -> None:
    for name in ("report", "report.xyz"):
        with pytest.raises(UnknownSuffixError) as caught:
            analysis.save(tmp_path / name)
        assert isinstance(caught.value, ConfigError)
        assert caught.value.suffixes == tuple(sorted(registry.SUFFIX_REPORTERS))
        assert caught.value.hint is not None
        assert ".html" in caught.value.hint
        assert not (tmp_path / name).exists()


def test_a_reporter_that_cannot_render_this_kind_writes_nothing(
    analysis: logfold.AnalysisResult, tmp_path: Path
) -> None:
    class DiffOnly:
        name = "diff-only"
        kinds = ("diff",)

        def render(self, result: object, **options: object) -> str:
            return "x"

    registry.register_reporter(DiffOnly())
    try:
        with pytest.raises(ConfigError, match="does not support analysis"):
            analysis.save(tmp_path / "x.out", "diff-only")
    finally:
        registry._reporters.pop("diff-only", None)
    assert not (tmp_path / "x.out").exists()


def test_a_reporter_that_returns_something_else_than_text_is_refused(
    analysis: logfold.AnalysisResult, tmp_path: Path
) -> None:
    class Broken:
        name = "broken"
        kinds = ("analysis",)

        def render(self, result: object, **options: object) -> bytes:
            return b"bytes"

    registry.register_reporter(Broken())  # type: ignore[arg-type]
    try:
        with pytest.raises(ConfigError, match="returned bytes, expected text"):
            analysis.save(tmp_path / "x.out", "broken")
    finally:
        registry._reporters.pop("broken", None)
    assert not (tmp_path / "x.out").exists()


def test_an_unwritable_destination_raises_oserror(analysis: logfold.AnalysisResult, tmp_path: Path) -> None:
    with pytest.raises(OSError, match=r"."):
        analysis.save(tmp_path / "missing-folder" / "report.json")


def test_reporter_for_suffix_is_public_in_ext() -> None:
    from logfold.ext import reporter_for_suffix

    assert reporter_for_suffix("a/b/report.CSV") == "csv"
    assert registry.SUFFIX_REPORTERS[".md"] == "markdown"


def test_info_reports_the_installation() -> None:
    facts = logfold.info()
    assert facts.version == logfold.__version__
    assert facts.python == sys.version.split()[0]
    assert facts.native_available == native.is_available()
    assert {"plain", "nginx", "logfmt"} <= set(facts.formats)
    assert {"json", "html", "text", "markdown", "csv"} <= set(facts.reporters)
    assert {"exact", "jaccard", "token_subset"} <= set(facts.matchers)
    assert facts.formats == tuple(sorted(facts.formats))
    assert facts == logfold.info()


def test_info_has_the_extension_versions_only_when_it_is_available() -> None:
    facts = logfold.info()
    versions = (facts.core_version, facts.contract_version, facts.algo_version)
    assert all(v is not None for v in versions) == facts.native_available
    assert all(v is None for v in versions) == (not facts.native_available)
    with pytest.raises(dataclasses.FrozenInstanceError):
        facts.version = "x"  # type: ignore[misc]


def test_is_saved_analysis_recognizes_a_report(analysis: logfold.AnalysisResult, tmp_path: Path) -> None:
    target = tmp_path / "result.json"
    analysis.to_json(target)
    assert logfold.is_saved_analysis(target) is True
    assert logfold.is_saved_analysis(str(target)) is True
    assert logfold.load_analysis(target).templates == analysis.templates


def test_is_saved_analysis_copes_with_a_bom_and_leading_space(tmp_path: Path) -> None:
    body = '{"schema_version": 1, "kind": "analysis", "templates": []}'
    bom = tmp_path / "bom.json"
    bom.write_bytes(b"\xef\xbb\xbf" + body.encode())
    spaced = tmp_path / "spaced.json"
    spaced.write_text("\n  " + body, encoding="utf-8")
    assert logfold.is_saved_analysis(bom) is True
    assert logfold.is_saved_analysis(spaced) is True


def test_a_utf16_file_counts_so_that_load_analysis_can_explain(tmp_path: Path) -> None:
    target = tmp_path / "utf16.json"
    target.write_text('{"schema_version": 1, "kind": "analysis"}', encoding="utf-16")
    assert logfold.is_saved_analysis(target) is True
    with pytest.raises(logfold.SourceError, match="UTF-16"):
        logfold.load_analysis(target)


def test_logs_and_other_json_are_not_saved_analyses(
    corpus_dir: Path, comparison: logfold.DiffResult, tmp_path: Path
) -> None:
    assert logfold.is_saved_analysis(corpus_dir / "app.log") is False
    assert logfold.is_saved_analysis(corpus_dir / "jsonl.log") is False
    target = tmp_path / "diff.json"
    comparison.to_json(target)
    assert logfold.is_saved_analysis(target) is False
    empty = tmp_path / "empty.json"
    empty.write_bytes(b"")
    assert logfold.is_saved_analysis(empty) is False
    assert logfold.is_saved_analysis(tmp_path / "missing.json") is False


def test_the_new_names_are_public() -> None:
    for name in ("info", "Info", "inspect_file", "Inspection", "InspectedRecord", "is_saved_analysis"):
        assert name in logfold.__all__
        assert hasattr(logfold, name)
    assert logfold.inspect_file is not None
