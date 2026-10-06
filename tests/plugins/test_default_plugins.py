"""The plugins that ship with logfold work without installing anything."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold.ext import registry
from logfold.plugins import CsvReporter, JaccardMatcher, MarkdownReporter

LOGFMT = """\
ts=2026-10-04T10:00:01Z level=info msg="user 41 logged in" ip=10.0.0.7
ts=2026-10-04T10:00:02Z level=info msg="user 42 logged in" ip=10.0.0.8
ts=2026-10-04T10:00:03Z level=warn msg="slow query" took=412ms
ts=2026-10-04T10:00:04Z level=error msg="upstream timed out" id=7
"""

SERILOG = """\
{"@t":"2026-10-04T10:00:01.123Z","@m":"User 41 logged in","@l":"Warning"}
{"@t":"2026-10-04T10:00:02.000Z","@m":"Cache warmed 5 keys"}
{"@t":"2026-10-04T10:00:03.000Z","@mt":"Payment 7 failed","@l":"Error"}
"""


def write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_default_plugins_are_registered_after_a_plain_import() -> None:
    assert {"logfmt", "serilog-clef"} <= set(registry.format_names())
    assert {"markdown", "csv"} <= set(registry.reporter_names())
    assert registry.get_matcher("jaccard").name == "jaccard"
    sources = {(kind, name): source for kind, name, source in registry.plugin_sources()}
    for key in (("format", "logfmt"), ("reporter", "csv"), ("matcher", "jaccard")):
        assert sources[key] == "built-in"


def test_logfmt_format(tmp_path: Path) -> None:
    result = logfold.analyze(write(tmp_path, "a.log", LOGFMT), format="logfmt", engine="python")
    assert result.run.unparsed == 0
    assert {t.text: (t.count, t.level) for t in result.templates} == {
        'msg="user <NUM> logged in" ip=<IP>': (2, "INFO"),
        'msg="slow query" took=412ms': (1, "WARN"),
        'msg="upstream timed out" id=<NUM>': (1, "ERROR"),
    }


def test_serilog_clef_format(tmp_path: Path) -> None:
    result = logfold.analyze(write(tmp_path, "a.jsonl", SERILOG), format="serilog-clef", engine="python")
    assert {t.text: t.level for t in result.templates} == {
        "User <NUM> logged in": "WARN",
        "Cache warmed <NUM> keys": None,
        "Payment <NUM> failed": "ERROR",
    }


@requires_native
@pytest.mark.parametrize(("name", "text"), [("logfmt", LOGFMT), ("serilog-clef", SERILOG)])
def test_native_and_python_engines_agree(tmp_path: Path, name: str, text: str) -> None:
    path = write(tmp_path, "a.log", text)
    native = logfold.analyze(path, format=name, engine="native")
    reference = logfold.analyze(path, format=name, engine="python")
    assert [(t.text, t.count, t.level) for t in native.templates] == [
        (t.text, t.count, t.level) for t in reference.templates
    ]


def test_auto_detection_does_not_pick_the_default_plugins(tmp_path: Path) -> None:
    path = write(tmp_path, "a.log", "2026-10-04T10:00:01Z [main] INFO hello 1\n" * 5)
    assert logfold.analyze(path, engine="python").meta.format == "app"


def test_markdown_reporter_tables_cannot_be_broken_by_log_content(tmp_path: Path) -> None:
    path = write(tmp_path, "a.log", "a|b `c` d\nline two 1\n")
    markdown = logfold.analyze(path, format="plain", engine="python").render("markdown")
    rows = [line for line in markdown.splitlines() if line.startswith("| ") and "`" in line]
    assert rows
    for row in rows:
        assert row.count("|") == 4
        assert row.count("`") == 2


def test_csv_reporter_neutralizes_spreadsheet_formulas(tmp_path: Path) -> None:
    path = write(tmp_path, "a.log", '=HYPERLINK("http://evil.example","x")\n-2+3\n')
    text = logfold.analyze(path, format="plain", engine="python").render("csv")
    cells = [row[-1] for row in csv.reader(io.StringIO(text))][1:]
    assert cells
    assert all(cell.startswith("'") for cell in cells)


def test_csv_and_markdown_reporters_render_a_diff_and_honour_top(tmp_path: Path) -> None:
    before = write(tmp_path, "b.log", LOGFMT)
    after = write(tmp_path, "a.log", LOGFMT.replace("slow query", "disk full"))
    result = logfold.diff(before, after, format="logfmt", engine="python", min_count=1)
    rows = list(csv.reader(io.StringIO(CsvReporter().render(result))))
    assert rows[0] == ["kind", "before_count", "after_count", "level", "template", "score", "p_value"]
    assert {row[0] for row in rows[1:]} == {"new", "disappeared"}
    assert len(list(csv.reader(io.StringIO(result.render("csv", top=1))))) == 3
    assert "## New templates" in MarkdownReporter().render(result)


def test_csv_top_below_one_means_all_rows(tmp_path: Path) -> None:
    result = logfold.analyze(write(tmp_path, "a.log", LOGFMT), format="logfmt", engine="python")
    assert result.render("csv", top=0).count("\n") == len(result.templates) + 1


def test_jaccard_matcher_pairs_the_closest_templates() -> None:
    matcher = JaccardMatcher()
    before = ['msg="retry failed after <NUM> attempts" id=<NUM>', "cache cleared", "x y"]
    after = ['msg="retry gave up after <NUM> attempts" id=<NUM>', "cache cleared now"]
    assert matcher.match(before, after) == [(0, 0), (1, 1)]
    assert matcher.match(["a b c"], ["x y z"]) == []
    assert matcher.match([], ["a"]) == []


def test_jaccard_matcher_makes_a_reworded_message_one_template(tmp_path: Path) -> None:
    before = write(tmp_path, "b.log", 'ts=2026-10-04T10:00:01Z level=error msg="retry failed after 3 attempts" id=7\n')
    after = write(tmp_path, "a.log", 'ts=2026-10-04T10:00:01Z level=error msg="retry gave up after 3 attempts" id=7\n')
    exact = logfold.diff(before, after, format="logfmt", engine="python", min_count=1, matcher="exact")
    assert (len(exact.new_templates), len(exact.disappeared)) == (1, 1)
    paired = logfold.diff(before, after, format="logfmt", engine="python", min_count=1)
    assert paired.config.matcher == "jaccard"
    assert (len(paired.new_templates), len(paired.disappeared)) == (0, 0)
