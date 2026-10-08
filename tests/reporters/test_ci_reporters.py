"""The github-summary and junit reporters."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import logfold
from corpora import hostile_pair, write
from logfold import ConfigError
from logfold.ext import registry
from logfold.model import DiffResult
from logfold.plugins.reporter_text import xml_text

CODE_SPAN = re.compile(r"`[^`]*`")


@pytest.fixture
def real_diff(corpus_dir: Path) -> DiffResult:
    return logfold.diff(
        str(corpus_dir / "app_before.log"), str(corpus_dir / "app_after.log"), format="app", engine="native"
    )


@pytest.fixture
def hostile_diff(tmp_path: Path) -> DiffResult:
    before, after = hostile_pair(tmp_path)
    return logfold.diff(str(before), str(after), format="app", engine="native")


def outside_code_spans(text: str) -> str:
    return CODE_SPAN.sub("", text)


def test_the_reporters_are_built_in() -> None:
    sources = {(kind, name): source for kind, name, source in registry.plugin_sources()}
    for name in ("github-summary", "junit"):
        assert sources[("reporter", name)] == "built-in"
    assert registry.get_reporter("junit").kinds == ("diff",)
    assert registry.get_reporter("github-summary").kinds == ("analysis", "diff")


def test_github_summary_of_a_diff(real_diff: DiffResult) -> None:
    text = real_diff.render("github-summary")
    assert re.match(r"## logfold: `[^`]*app_before\.log` -> `[^`]*app_after\.log`\n", text)
    assert f"**{len(real_diff.new_alerts):,} new WARN+ template" in text
    assert "| new | WARN+ | disappeared | changed | unchanged | records |" in text
    assert "### New templates" in text
    assert "- **ERROR** 80 `database connection lost to replica<NUM>`" in text
    assert text.endswith("\n")


def test_github_summary_lists_alerts_before_other_templates(real_diff: DiffResult) -> None:
    lines = [line for line in real_diff.render("github-summary").splitlines() if line.startswith("- ")]
    levels = [re.match(r"- (?:\*\*(\w+)\*\* )?", line).group(1) for line in lines[: len(real_diff.new_templates)]]  # type: ignore[union-attr]
    alerts = [level in ("WARN", "ERROR", "FATAL") for level in levels]
    assert alerts == sorted(alerts, reverse=True)


def test_github_summary_of_an_analysis(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app", engine="native")
    text = result.render("github-summary", top=3)
    assert re.match(r"## logfold: `[^`]*app\.log`\n", text)
    assert "### Most frequent templates (3 of " in text
    assert len([line for line in text.splitlines() if line.startswith("- ")]) == 3


def test_github_summary_collapses_the_secondary_lists(real_diff: DiffResult) -> None:
    text = real_diff.render("github-summary")
    assert "<details><summary>" in text
    assert text.count("<details>") == text.count("</details>")
    for line in text.splitlines():
        if line.startswith("<details>"):
            assert re.fullmatch(r"<details><summary>(Changed|Disappeared) templates \([\d,]+\)</summary>", line)


def letters(number: int) -> str:
    word = ""
    while True:
        number, digit = divmod(number, 26)
        word += chr(97 + digit)
        if number == 0:
            return word


@pytest.fixture
def many_new_templates(tmp_path: Path) -> DiffResult:
    quiet = [f"2026-10-04T12:00:00Z INFO request {i} served" for i in range(10)]
    noisy = [
        f"2026-10-04T12:00:01Z ERROR {letters(i)} {letters(i + 7000)} {letters(i + 9000)} {letters(i + 11000)} failed"
        for i in range(300)
    ]
    before = write(tmp_path / "before.log", quiet)
    after = write(tmp_path / "after.log", quiet + noisy)
    return logfold.diff(str(before), str(after), format="app", engine="native")


def test_github_summary_keeps_to_its_byte_budget(many_new_templates: DiffResult) -> None:
    assert len(many_new_templates.new_templates) >= 100
    full = many_new_templates.render("github-summary", top=100000)
    budget = len(full.encode("utf-8")) // 2
    text = many_new_templates.render("github-summary", top=100000, max_bytes=budget)
    assert len(text.encode("utf-8")) <= budget
    assert "to fit the size limit of a job summary" in text
    assert "to fit the size limit" not in full


def test_github_summary_with_a_tiny_budget_still_gives_the_counts(real_diff: DiffResult) -> None:
    text = real_diff.render("github-summary", max_bytes=1)
    assert "| new | WARN+ |" in text
    assert "### New templates (0 of " in text


def test_github_summary_neutralizes_hostile_text(hostile_diff: DiffResult) -> None:
    text = hostile_diff.render("github-summary")
    prose = outside_code_spans(text)
    for danger in ("<script", "<img", "@channel", "<!here>", "](http", "\x1b", "\x07", "\x01"):
        assert danger not in prose, danger
    assert "\\x1b" in text
    assert not any(line.startswith("::") for line in text.splitlines())
    assert all(line.count("`") % 2 == 0 for line in text.splitlines())
    assert "rm -rf" in text


def test_github_summary_can_be_appended_but_junit_cannot(hostile_diff: DiffResult, tmp_path: Path) -> None:
    out = tmp_path / "summary.md"
    hostile_diff.save(out, "github-summary", append=True)
    hostile_diff.save(out, "github-summary", append=True)
    assert out.read_text(encoding="utf-8").count("## logfold: ") == 2
    with pytest.raises(ConfigError, match="cannot be appended"):
        hostile_diff.save(tmp_path / "r.xml", append=True)


def parse(text: str) -> ET.Element:
    return ET.fromstring(text.encode("utf-8"))


def test_junit_fails_each_new_alert(real_diff: DiffResult) -> None:
    suite = parse(real_diff.render("junit")).find("testsuite")
    assert suite is not None
    alerts = real_diff.new_alerts
    failed = [case for case in suite.iter("testcase") if case.find("failure") is not None]
    assert len(failed) == len(alerts) == int(suite.get("failures", "-1"))
    assert int(suite.get("tests", "-1")) == len(list(suite.iter("testcase")))
    case = next(c for c in failed if "database connection lost" in c.get("name", ""))
    assert case.get("classname") == "logfold.new.ERROR"
    failure = case.find("failure")
    assert failure is not None
    assert failure.get("type") == "ERROR"
    assert "records: 80" in (failure.text or "")


def test_junit_new_templates_below_warn_pass(hostile_diff: DiffResult) -> None:
    assert len(hostile_diff.new_templates) > len(hostile_diff.new_alerts)
    suite = parse(hostile_diff.render("junit", top=1)).find("testsuite")
    assert suite is not None
    passing = [c for c in suite.iter("testcase") if c.find("failure") is None]
    assert len(passing) == 1
    assert all(c.get("classname", "").startswith("logfold.new.") for c in passing)


def test_junit_names_are_unique(real_diff: DiffResult) -> None:
    suite = parse(real_diff.render("junit", top=1000)).find("testsuite")
    assert suite is not None
    names = [case.get("name") for case in suite.iter("testcase")]
    assert len(names) == len(set(names))


def test_junit_of_a_diff_without_new_templates_has_one_passing_case(corpus_dir: Path) -> None:
    path = str(corpus_dir / "app_before.log")
    suite = parse(logfold.diff(path, path, format="app", engine="native").render("junit")).find("testsuite")
    assert suite is not None
    assert suite.get("failures") == "0"
    cases = list(suite.iter("testcase"))
    assert [c.get("name") for c in cases] == ["no new templates"]
    assert cases[0].find("failure") is None


def test_junit_records_the_counts_as_properties(real_diff: DiffResult) -> None:
    root = parse(real_diff.render("junit"))
    properties = {p.get("name"): p.get("value") for p in root.iter("property")}
    assert properties["before"].endswith("app_before.log")
    assert properties["new_templates"] == str(len(real_diff.new_templates))
    assert properties["unchanged_templates"] == str(real_diff.unchanged)


def test_junit_survives_hostile_text(hostile_diff: DiffResult) -> None:
    text = hostile_diff.render("junit")
    root = parse(text)
    names = [case.get("name", "") for case in root.iter("testcase")]
    assert any("<script>" in name for name in names)
    assert not any(ord(char) < 32 and char not in "\t\n\r" for char in text)
    assert chr(0xFFFE) not in text
    assert "U+FFFE" in text
    assert len(list(root.iter("failure"))) == len(hostile_diff.new_alerts)


def test_junit_refuses_an_analysis(corpus_dir: Path) -> None:
    result = logfold.analyze(str(corpus_dir / "app.log"), format="app", engine="native")
    with pytest.raises(ConfigError, match="does not support analysis"):
        result.render("junit")


def test_the_xml_suffix_selects_junit(real_diff: DiffResult, tmp_path: Path) -> None:
    out = tmp_path / "logfold.xml"
    real_diff.save(out)
    assert parse(out.read_text(encoding="utf-8")).tag == "testsuites"


def test_xml_text_shows_what_xml_cannot_hold() -> None:
    cleaned = xml_text("a" + chr(0) + chr(0xFFFF) + chr(0xFFFE) + "\x1b" + "b\tc\nd", 200)
    assert cleaned == "a\\x00U+FFFFU+FFFE\\x1bb c d"
    assert xml_text("x" * 50, 10) == "xxxxxxx..."
