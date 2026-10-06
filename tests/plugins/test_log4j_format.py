"""Conversion of log4j and logback patterns into regex formats."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from logfold.errors import FormatError
from logfold.ext import log4j_format
from logfold.formats import resolve_format

LOGBACK = """\
12:00:00.123 [main] INFO  com.shop.App - started in 3 s
12:00:01.456 [http-nio-8080-exec-1] ERROR com.shop.OrderService - order 17 failed
12:00:02.000 [pool-1-thread-3] WARN  com.shop.Cache - evicted 5 keys
"""


def write(tmp_path: Path, text: str) -> str:
    path = tmp_path / "app.log"
    path.write_text(text, encoding="utf-8", newline="\n")
    return str(path)


def test_the_default_pattern_has_all_three_groups() -> None:
    spec = log4j_format("%d{ISO8601} %-5p [%t] %c - %m%n")
    assert (spec.message_group, spec.time_group, spec.level_group) == ("msg", "ts", "lvl")
    assert spec.multiline
    assert spec.pattern.endswith("(?P<msg>.*)$")
    line = "2026-10-06 12:00:00,123 INFO  [main] com.shop.App - started"
    match = re.search(spec.pattern, line)
    assert match is not None
    assert match.group("lvl") == "INFO"
    assert match.group("msg") == "started"


def test_a_logback_pattern_reads_a_log(tmp_path: Path) -> None:
    spec = log4j_format("%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n")
    assert spec.ts_format == "%H:%M:%S.%f"
    result = logfold.analyze(write(tmp_path, LOGBACK), format=spec, engine="python")
    assert (result.run.records, result.run.unparsed, result.run.untimed) == (3, 0, 0)
    assert {t.text: t.level for t in result.templates} == {
        "started in <NUM> s": "INFO",
        "order <NUM> failed": "ERROR",
        "evicted <NUM> keys": "WARN",
    }


@requires_native
def test_a_converted_pattern_gives_the_same_result_in_both_engines(tmp_path: Path) -> None:
    path = write(tmp_path, LOGBACK)
    spec = log4j_format("%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n")
    native = logfold.analyze(path, format=spec, engine="native")
    reference = logfold.analyze(path, format=spec, engine="python")
    assert [(t.text, t.count, t.level) for t in native.templates] == [
        (t.text, t.count, t.level) for t in reference.templates
    ]


def test_the_log4j_prefix_resolves_like_a_registered_format(tmp_path: Path) -> None:
    resolved = resolve_format("log4j:%d{HH:mm:ss.SSS} %p %m%n", [])
    assert resolved.spec.name == "log4j"
    result = logfold.analyze(write(tmp_path, "12:00:00.123 INFO started 1\n"), format="log4j:%d{HH:mm:ss.SSS} %p %m%n")
    assert [t.text for t in result.templates] == ["started <NUM>"]


@pytest.mark.parametrize(
    ("date", "line", "ts_format"),
    [
        ("yyyy-MM-dd'T'HH:mm:ss.SSSXXX", "2026-10-06T12:00:00.123+03:00 INFO x", "%Y-%m-%dT%H:%M:%S.%f%z"),
        ("dd MMM yyyy HH:mm:ss,SSS", "06 Oct 2026 12:00:00,123 INFO x", "%d %b %Y %H:%M:%S,%f"),
        ("ABSOLUTE", "12:00:00,123 INFO x", "%H:%M:%S,%f"),
        ("DATE", "06 Oct 2026 12:00:00,123 INFO x", "%d %b %Y %H:%M:%S,%f"),
        ("ISO8601", "2026-10-06T12:00:00,123 INFO x", None),
    ],
)
def test_date_patterns(date: str, line: str, ts_format: str | None) -> None:
    spec = log4j_format(f"%d{{{date}}} %p %m")
    assert spec.ts_format == ts_format
    match = re.search(spec.pattern, line)
    assert match is not None
    assert match.group("lvl") == "INFO"


def test_date_defaults_to_iso8601() -> None:
    spec = log4j_format("%d %p %m")
    assert re.search(spec.pattern, "2026-10-06 12:00:00,123 INFO x") is not None


def test_width_modifiers_are_padding() -> None:
    left = re.search(log4j_format("%-5p|%m").pattern, "WARN |x")
    right = re.search(log4j_format("%5p|%m").pattern, " WARN|x")
    both = re.search(log4j_format("%-5.5p|%m").pattern, "INFO |x")
    assert [m is not None and m.group("lvl") for m in (left, right, both)] == ["WARN", "WARN", "INFO"]


def test_percent_literal_and_message_in_the_middle() -> None:
    spec = log4j_format("%p 100%% %m [%X{user}]")
    assert not spec.pattern.endswith("$")
    match = re.search(spec.pattern, "INFO 100% done [bob]")
    assert match is not None
    assert match.group("msg") == "done"


def test_throwable_converters_print_nothing_in_the_line() -> None:
    plain = log4j_format("%p %m%n")
    with_trace = log4j_format("%p %m%ex%n")
    assert plain.pattern == with_trace.pattern


def test_without_a_message_the_whole_line_is_the_message() -> None:
    spec = log4j_format("%d{ABSOLUTE} %p")
    assert spec.message_group is None


def test_a_field_that_repeats_is_not_captured_twice() -> None:
    assert re.compile(log4j_format("%p %p %m").pattern).groupindex.keys() == {"lvl", "msg"}


def test_literal_characters_that_are_special_in_a_regex_are_escaped() -> None:
    spec = log4j_format("(%p) [%t] {%m}")
    assert re.search(spec.pattern, "(INFO) [main] {hello}") is not None


@pytest.mark.parametrize(
    "pattern",
    ["%highlight{%p}{INFO=green} %m", "%q %m", "%d{EEE} %m", "%d{yyyy z} %m", "%n%m", "%d{HH'mm} %m", "%", "", "%n"],
)
def test_unsupported_patterns_are_refused_with_a_hint(pattern: str) -> None:
    with pytest.raises(FormatError) as raised:
        log4j_format(pattern)
    assert str(raised.value)
    assert pattern in str(raised.value)


def test_the_error_names_the_whole_converter() -> None:
    with pytest.raises(FormatError, match="'%highlight'"):
        log4j_format("%highlight{%p} %m")


def test_unsupported_converter_hint_names_the_way_out() -> None:
    with pytest.raises(FormatError) as raised:
        log4j_format("%highlight{%p} %m")
    assert raised.value.hint is not None
    assert "regex:" in raised.value.hint
