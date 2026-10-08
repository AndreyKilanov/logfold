"""The chat-message and prometheus reporters."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from prometheus_client.parser import text_string_to_metric_families

import logfold
from corpora import hostile_pair
from logfold import ConfigError
from logfold.ext import registry
from logfold.model import AnalysisResult, DiffResult

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


@pytest.fixture
def analysis(corpus_dir: Path) -> AnalysisResult:
    return logfold.analyze(str(corpus_dir / "app.log"), format="app", engine="native")


def families(text: str) -> dict[str, list[tuple[dict[str, str], float]]]:
    parsed = {}
    for family in text_string_to_metric_families(text):
        assert family.type == "gauge"
        parsed[family.name] = [(dict(sample.labels), sample.value) for sample in family.samples]
    return parsed


def test_the_reporters_are_built_in() -> None:
    sources = {(kind, name): source for kind, name, source in registry.plugin_sources()}
    for name in ("chat-message", "prometheus"):
        assert sources[("reporter", name)] == "built-in"
        assert registry.get_reporter(name).kinds == ("analysis", "diff")


def test_chat_message_of_a_diff(real_diff: DiffResult) -> None:
    lines = real_diff.render("chat-message").splitlines()
    assert re.fullmatch(r"logfold: `[^`]*app_before\.log` -> `[^`]*app_after\.log`", lines[0])
    assert lines[1] == "1 new WARN+ template of 1 new, 0 disappeared, 1 changed."
    assert lines[2] == "New templates:"
    assert lines[3] == "- ERROR 80 x `database connection lost to replica<NUM>`"


def test_chat_message_of_an_analysis(analysis: AnalysisResult) -> None:
    lines = analysis.render("chat-message", top=2).splitlines()
    assert lines[1].startswith(f"{analysis.run.records:,} records, {len(analysis.templates):,} templates")
    assert lines[2] == "Most frequent templates:"
    assert len([line for line in lines if line.startswith("- ")]) == 2
    assert lines[-1] == f"... and {len(analysis.templates) - 2:,} more"


def test_chat_message_lists_alerts_first(hostile_diff: DiffResult) -> None:
    items = [line for line in hostile_diff.render("chat-message", top=100).splitlines() if line.startswith("- ")]
    assert items[-1].startswith("- INFO ")
    assert all(item.split()[1] in ("WARN", "ERROR", "FATAL") for item in items[:-1])


def test_chat_message_keeps_within_its_length(hostile_diff: DiffResult) -> None:
    full = hostile_diff.render("chat-message", top=100)
    limit = len(full) - 80
    text = hostile_diff.render("chat-message", top=100, max_chars=limit)
    assert len(text) <= limit + 1
    assert re.search(r"\.\.\. and \d+ more\n$", text)
    assert "... and" not in full


def test_chat_message_neutralizes_hostile_text(hostile_diff: DiffResult) -> None:
    text = hostile_diff.render("chat-message", top=100)
    prose = CODE_SPAN.sub("", text)
    for danger in ("<script", "@channel", "<!here>", "](http", "\x1b", "\x07", "\x01"):
        assert danger not in prose, danger
    for mention in ("@channel", "<!here>"):
        assert mention not in text, mention
    assert "@" + chr(0x200B) + "channel" in text
    assert "<" + chr(0x200B) + "!here>" in text
    assert "\\x1b" in text
    assert not any(line.startswith("::") for line in text.splitlines())
    assert all(line.count("`") % 2 == 0 for line in text.splitlines())


def test_chat_message_with_nothing_new_says_so(corpus_dir: Path) -> None:
    path = str(corpus_dir / "app_before.log")
    text = logfold.diff(path, path, format="app", engine="native").render("chat-message")
    assert "0 new WARN+ templates of 0 new, 0 disappeared, 0 changed." in text
    assert "New templates:" not in text


def test_prometheus_of_a_diff(real_diff: DiffResult) -> None:
    parsed = families(real_diff.render("prometheus"))
    assert parsed["logfold_diff_records"] == [
        ({"side": "before"}, real_diff.before.records),
        ({"side": "after"}, real_diff.after.records),
    ]
    templates = {labels["change"]: value for labels, value in parsed["logfold_diff_templates"]}
    assert templates == {
        "new": len(real_diff.new_templates),
        "disappeared": len(real_diff.disappeared),
        "changed": len(real_diff.changed),
        "unchanged": real_diff.unchanged,
    }
    assert parsed["logfold_diff_new_alerts"] == [({}, len(real_diff.new_alerts))]
    error = [
        (labels, value)
        for labels, value in parsed["logfold_diff_template_records"]
        if labels["template"].startswith("database connection lost") and labels["side"] == "after"
    ]
    assert error[0][0]["change"] == "new"
    assert error[0][0]["level"] == "ERROR"
    assert error[0][1] == 80


def test_prometheus_of_an_analysis(analysis: AnalysisResult) -> None:
    parsed = families(analysis.render("prometheus", top=3))
    assert parsed["logfold_records"] == [({}, analysis.run.records)]
    assert parsed["logfold_unparsed_lines"] == [({}, analysis.run.unparsed)]
    assert parsed["logfold_templates"] == [({}, len(analysis.templates))]
    assert {labels["level"]: value for labels, value in parsed["logfold_level_records"]} == dict(analysis.levels)
    series = parsed["logfold_template_records"]
    assert [value for _, value in series] == [t.count for t in analysis.top(3)]
    assert [labels["id"] for labels, _ in series] == [t.id for t in analysis.top(3)]


def test_prometheus_levels_come_in_severity_order(analysis: AnalysisResult) -> None:
    names = [labels["level"] for labels, _ in families(analysis.render("prometheus"))["logfold_level_records"]]
    assert names == sorted(names, key=("TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL").index)


def test_prometheus_bounds_the_template_series_by_top(real_diff: DiffResult, analysis: AnalysisResult) -> None:
    assert len(families(analysis.render("prometheus", top=2))["logfold_template_records"]) == 2
    diff_series = families(real_diff.render("prometheus", top=1))["logfold_diff_template_records"]
    sections = sum(1 for entries in (real_diff.new_templates, real_diff.changed, real_diff.disappeared) if entries)
    assert len(diff_series) == 2 * sections
    assert len(families(analysis.render("prometheus", top=0)).get("logfold_template_records", [])) == 0


def test_prometheus_labels_survive_hostile_text(hostile_diff: DiffResult) -> None:
    text = hostile_diff.render("prometheus", top=100)
    series = families(text)["logfold_diff_template_records"]
    assert not any(ord(char) < 32 and char != "\n" for char in text)
    assert text.endswith("\n")
    sent = {labels["template"] for labels, _ in series}
    assert any("C:" + chr(92) + "tmp" + chr(92) + '"x"' in template for template in sent)
    assert any("<script>" in template for template in sent)
    assert len({tuple(sorted(labels.items())) for labels, _ in series}) == len(series)


def test_prometheus_series_are_unique_per_template_and_side(real_diff: DiffResult) -> None:
    series = families(real_diff.render("prometheus"))["logfold_diff_template_records"]
    keys = [(labels["change"], labels["id"], labels["side"]) for labels, _ in series]
    assert len(keys) == len(set(keys))


def test_the_prom_suffix_selects_prometheus(real_diff: DiffResult, tmp_path: Path) -> None:
    out = tmp_path / "logfold.prom"
    real_diff.save(out)
    assert "logfold_diff_new_alerts" in out.read_text(encoding="utf-8")
    with pytest.raises(ConfigError, match="cannot be appended"):
        real_diff.save(out, append=True)


def test_chat_message_can_be_appended(real_diff: DiffResult, tmp_path: Path) -> None:
    out = tmp_path / "message.txt"
    real_diff.save(out, "chat-message", append=True)
    real_diff.save(out, "chat-message", append=True)
    assert out.read_text(encoding="utf-8").count("logfold: ") == 2


def test_defuse_mentions_changes_only_the_mention_syntax() -> None:
    from logfold.plugins.reporter_text import defuse_mentions

    zws = chr(0x200B)
    assert defuse_mentions("a <!channel> <@U1> <#C1> @here @ALL @everyone b") == (
        f"a <{zws}!channel> <{zws}@U1> <{zws}#C1> @{zws}here @{zws}ALL @{zws}everyone b"
    )
    assert defuse_mentions("ERROR user@example.com <NUM> <*> @channels") == "ERROR user@example.com <NUM> <*> @channels"
