"""The server, database, container and CI formats that ship with logfold."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold.ext import registry

BOM = "\N{ZERO WIDTH NO-BREAK SPACE}"
TAB = "\N{CHARACTER TABULATION}"


def lines(*rows: str) -> str:
    return "\n".join(rows) + "\n"


HAPROXY = lines(
    "Oct  6 12:00:00 lb1 haproxy[1234]: 192.168.1.5:51234 [06/Oct/2026:12:00:00.123] fe_http be_app/srv1 "
    '0/0/1/12/13 200 1534 - - ---- 3/3/0/0/0 0/0 "GET /index.html HTTP/1.1"',
    "<134>Oct  6 12:00:01 lb1 haproxy[1234]: 192.168.1.6:51235 [06/Oct/2026:12:00:01.456] fe_http be_app/srv2 "
    '0/0/1/12/13 502 212 - - sH-- 3/3/0/0/0 0/0 {example.com|curl} "GET /api/v1/items/17 HTTP/1.1"',
    "192.168.1.7:51236 [06/Oct/2026:12:00:02.000] fe_http be_app/srv1 "
    '0/0/1/12/13 200 1534 - - ---- 3/3/0/0/0 0/0 "GET /index.html HTTP/1.1"',
    "10.0.0.1:5000 [06/Oct/2026:12:00:03.000] fe_tcp be_db/srv1 1/0/3 1234 -- 1/1/0/0/0 0/0",
)

POSTGRESQL = lines(
    "2026-10-06 12:00:00.123 UTC [1234] LOG:  checkpoint starting: time",
    '2026-10-06 12:00:01.123 UTC [1301] app@shop ERROR:  duplicate key value violates unique constraint "users_pkey"',
    "2026-10-06 12:00:01.123 UTC [1301] app@shop DETAIL:  Key (id)=(41) already exists.",
    "2026-10-06 12:00:01.123 UTC [1301] app@shop STATEMENT:  INSERT INTO users (id, name)",
    f"{TAB}VALUES (41, 'bob')",
    "2026-10-06 12:00:02 UTC [1302] FATAL:  terminating connection due to administrator command",
    "2026-10-06 12:00:03 MSK:10.0.0.7(5432):app@shop:[1303]:WARNING:  there is already a transaction in progress",
    "2026-10-06 12:00:04.000 +03 [1304] DEBUG1:  proc_exit(0)",
)

POSTGRESQL_CSV = lines(
    "2026-10-06 12:00:00.123 UTC,,,1234,,65a1b2c3.4d2,1,,2026-10-06 11:59:00 UTC,,0,LOG,00000,"
    '"checkpoint starting: time",,,,,,,,,"","checkpointer"',
    '2026-10-06 12:00:01.123 UTC,"app","shop",1301,"10.0.0.7:5432",65a1b2c3.515,4,"INSERT",'
    "2026-10-06 11:59:00 UTC,3/12,0,ERROR,23505,"
    '"duplicate key value violates unique constraint ""users_pkey""","Key (id)=(41), (x) already exists.",,,,,'
    '"INSERT INTO users (id, name)',
    """VALUES (41, 'bob')",,,"psql","client backend\"""",
    '2026-10-06 12:00:02.000 UTC,"app","shop",1302,"10.0.0.7:5433",65a1b2c3.516,1,"idle",'
    "2026-10-06 11:59:00 UTC,3/13,0,WARNING,01000,"
    '"there is already a transaction in progress",,,,,,,,,"psql","client backend"',
)

DOCKER_LINES = [
    {"log": "user 41 logged in\n", "stream": "stdout", "time": "2026-10-06T12:00:00.123456789Z"},
    {"log": "user 42 logged in\n", "stream": "stdout", "time": "2026-10-06T12:00:01.5Z"},
    {"log": "disk 7 full\n", "stream": "stderr", "time": "2026-10-06T12:00:02.000000001Z"},
]

GITHUB_ACTIONS = lines(
    f"{BOM}2026-10-06T12:00:00.1234567Z ##[group]Run actions/checkout@v4",
    "2026-10-06T12:00:01.0000000Z Syncing repository 5",
    "2026-10-06T12:00:02.0000000Z ##[endgroup]",
    "2026-10-06T12:00:03.0000000Z ##[warning]Node 16 is deprecated",
    "2026-10-06T12:00:04.0000000Z ##[debug]cache key is abc",
    "2026-10-06T12:00:05.0000000Z ##[error]Process completed with exit code 1.",
)

LOG4J = lines(
    "2026-10-06 12:00:00,123 INFO  [main] com.shop.App - started in 3 s",
    "2026-10-06 12:00:01,456 ERROR [http-nio-8080-exec-1] com.shop.OrderService - order 17 failed",
    "java.lang.IllegalStateException: boom",
    f"{TAB}at com.shop.OrderService.place(OrderService.java:42)",
    f"{TAB}at com.shop.Web.handle(Web.java:7)",
    "2026-10-06 12:00:02,000 WARN  [pool-1-thread-3] c.s.Cache - evicted 5 keys",
)

SAMPLES = {
    "haproxy": HAPROXY,
    "postgresql": POSTGRESQL,
    "postgresql-csv": POSTGRESQL_CSV,
    "docker-json": "".join(json.dumps(row) + "\n" for row in DOCKER_LINES),
    "github-actions": GITHUB_ACTIONS,
    "log4j": LOG4J,
}


def write(tmp_path: Path, name: str, text: str) -> str:
    path = tmp_path / f"{name}.log"
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)


def analyze(tmp_path: Path, name: str, engine: str = "python", **options: object) -> logfold.AnalysisResult:
    path = write(tmp_path, name, SAMPLES[name])
    return logfold.analyze(path, format=name, engine=engine, **options)  # type: ignore[arg-type]


def templates(result: logfold.AnalysisResult) -> dict[str, tuple[int, str | None]]:
    return {t.text: (t.count, t.level) for t in result.templates}


def test_the_formats_are_registered_as_built_in() -> None:
    sources = {(kind, name): source for kind, name, source in registry.plugin_sources()}
    for name in SAMPLES:
        assert sources[("format", name)] == "built-in"


@pytest.mark.parametrize("name", list(SAMPLES))
def test_every_line_parses_and_has_a_time(tmp_path: Path, name: str) -> None:
    result = analyze(tmp_path, name)
    assert result.run.unparsed == 0
    assert result.run.untimed == 0
    assert result.meta.format == name


@requires_native
@pytest.mark.parametrize("name", list(SAMPLES))
def test_native_and_python_engines_agree(tmp_path: Path, name: str) -> None:
    native = analyze(tmp_path, name, "native")
    reference = analyze(tmp_path, name, "python")
    assert [(t.text, t.count, t.level) for t in native.templates] == [
        (t.text, t.count, t.level) for t in reference.templates
    ]
    assert native.run == reference.run


def test_haproxy_with_and_without_the_syslog_prefix(tmp_path: Path) -> None:
    result = analyze(tmp_path, "haproxy")
    found = templates(result)
    assert len(found) == 3
    index_page = (
        'fe_http be_app/srv1 <NUM><PATH> <NUM> <NUM> - - ---- <NUM><PATH> <NUM>/<NUM> "GET /index.html HTTP/<NUM>"'
    )
    assert found[index_page] == (2, None)
    assert any("sH--" in text for text in found)
    assert any(text.startswith("fe_tcp be_db/srv1") for text in found)
    assert result.run.records == 4


def test_haproxy_accept_time_selects_a_window(tmp_path: Path) -> None:
    result = analyze(tmp_path, "haproxy", since="2026-10-06T12:00:02")
    assert result.run.records == 2


def test_postgresql_stderr_prefixes_levels_and_continuation_lines(tmp_path: Path) -> None:
    found = templates(analyze(tmp_path, "postgresql"))
    assert found == {
        "checkpoint starting: time": (1, None),
        'duplicate key value violates unique constraint "users_pkey"': (1, "ERROR"),
        "Key (id)=(<NUM>) already exists.": (1, None),
        "INSERT INTO users (id, name) VALUES (<NUM>, 'bob')": (1, None),
        "terminating connection due to administrator command": (1, "FATAL"),
        "there is already a transaction in progress": (1, "WARN"),
        "proc_exit(<NUM>)": (1, None),
    }


def test_postgresql_csv_reads_severity_and_message_columns(tmp_path: Path) -> None:
    result = analyze(tmp_path, "postgresql-csv")
    levels = {t.level for t in result.templates}
    assert levels == {None, "ERROR", "WARN"}
    assert result.run.records == 3
    error = next(t for t in result.templates if t.level == "ERROR")
    assert error.text.startswith('duplicate key value violates unique constraint ""users_pkey""')


def test_docker_json_drops_the_line_break_and_the_stream(tmp_path: Path) -> None:
    result = analyze(tmp_path, "docker-json")
    assert templates(result) == {"user <NUM> logged in": (2, None), "disk <NUM> full": (1, None)}


def test_github_actions_levels_commands_and_the_byte_order_mark(tmp_path: Path) -> None:
    found = templates(analyze(tmp_path, "github-actions"))
    assert found == {
        "##[group]Run actions/checkout@v4": (1, None),
        "Syncing repository <NUM>": (1, None),
        "##[endgroup]": (1, None),
        "Node <NUM> is deprecated": (1, "WARN"),
        "cache key is abc": (1, "DEBUG"),
        "Process completed with exit code <NUM>.": (1, "ERROR"),
    }


def test_log4j_stack_trace_joins_its_record(tmp_path: Path) -> None:
    result = analyze(tmp_path, "log4j")
    assert result.run.records == 3
    levels = {t.level: t.text for t in result.templates}
    assert levels["ERROR"].startswith("order <NUM> failed java.lang.IllegalStateException: boom at com.shop.Order")
    assert levels["WARN"] == "evicted <NUM> keys"


def test_log4j_without_multiline_leaves_the_trace_lines_unparsed(tmp_path: Path) -> None:
    path = write(tmp_path, "log4j", LOG4J)
    result = logfold.analyze(path, format="log4j", engine="python", multiline=False)
    assert (result.run.records, result.run.unparsed) == (3, 3)


def test_diff_between_two_runs_of_a_new_format(tmp_path: Path) -> None:
    before = write(tmp_path, "before", POSTGRESQL)
    extra = "2026-10-06 12:00:09 UTC [1] ERROR:  deadlock detected\n"
    after = write(tmp_path, "after", POSTGRESQL + extra)
    result = logfold.diff(before, after, format="postgresql", engine="python", min_count=1)
    assert [t.text for t in result.new_templates] == ["deadlock detected"]
