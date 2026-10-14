"""The access-log and error-log formats read the forms that other projects' real logs have.

The lines are from the test logs of the Filebeat modules (``elastic/beats``, Apache-2.0), shortened.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import logfold

ACCESS_FORMS = [
    '::1 - - [26/Dec/2016:16:16:29 +0200] "GET /favicon.ico HTTP/1.1" 404 209',
    'vhost1.domaine.fr 192.168.33.2 - - [26/Dec/2016:16:22:14 +0000] "GET /hello HTTP/1.1" 404 499 "-" "Mozilla/5.0"',
    '10.0.0.2, 10.0.0.1, 127.0.0.1 - - [07/Dec/2016:11:05:07 +0100] "GET /ocelot HTTP/1.1" 200 571 "-" "Mozilla/5.0"',
    '"10.5.102.222, 175.16.199.1" 10.2.1.185 - - [22/Jan/2016:13:18:29 +0000] "GET /assets/x?q=100 HTTP/1.1" 200 25507',
    'example.com 10.0.0.2, 10.0.0.1 - - [07/Dec/2016:11:05:07 +0100] "GET /ocelot HTTP/1.1" 200 571 "-" "Mozilla/5.0"',
    '2a02:cf40::8000, 10.225.192.17 10.2.2.121 - - [30/Dec/2016:06:47:09 +0000] "GET /test.html HTTP/1.1" 404 8571',
    '127.0.0.1 - - [12/Apr/2018:09:48:40 +0200] "" 400 0 "-" "-"',
    'unix: - - [26/Feb/2019:15:39:42 +0100] "hello" 400 173 "-" "-"',
]


@pytest.mark.parametrize("name", ["nginx", "apache"])
def test_access_log_forms_with_a_host_or_a_list_of_addresses(tmp_path: Path, name: str) -> None:
    path = tmp_path / "access.log"
    path.write_text("\n".join(ACCESS_FORMS) + "\n", encoding="utf-8", newline="\n")
    seen = logfold.inspect_file(path, format=name)
    assert (seen.records, seen.unparsed) == (len(ACCESS_FORMS), 0)
    assert seen.first_time is not None
    assert [record.message for record in seen.shown][:2] == [
        '"GET /favicon.ico HTTP/1.1" 404',
        '"GET /hello HTTP/1.1" 404',
    ]


def test_a_bracket_that_is_not_a_date_does_not_make_an_access_record(tmp_path: Path) -> None:
    path = tmp_path / "other.log"
    path.write_text('x [main] "GET /" 200\n', encoding="utf-8", newline="\n")
    assert logfold.inspect_file(path, format="nginx").records == 0


def test_nginx_error_joins_the_lines_that_follow_an_entry(tmp_path: Path) -> None:
    text = (
        '2019/10/30 23:26:34 [error] 205860#205860: *1 FastCGI sent in stderr: "PHP message: PHP Warning: a\n'
        "PHP message: PHP Warning: b\n"
        'PHP message: PHP Warning: c" while reading response header\n'
        "2019/11/05 14:50:44 [error] 54053#0: *3 open() failed\n"
    )
    path = tmp_path / "error.log"
    path.write_text(text, encoding="utf-8", newline="\n")
    seen = logfold.inspect_file(path, format="nginx-error")
    assert (seen.records, seen.unparsed) == (2, 0)
    assert [record.lines for record in seen.shown] == [3, 1]


def test_syslog_reads_the_classic_and_the_iso_time_and_joins_continuation_lines(tmp_path: Path) -> None:
    text = (
        "Dec 13 11:35:28 mac GoogleUpdate[21412]: first\n"
        "\t\tticketStore=<KSPersistentTicketStore:0x100204520\n"
        "2018-08-14T14:30:02.203151+02:00 linux systemd[4179]: Stopped target Basic System.\n"
        "1986-04-26T01:23:45.101+0400 rmbk shutdown[2649]: shutting down\n"
        "2019-06-14T10:40:20.912134 localhost sudo: no offset\n"
    )
    path = tmp_path / "syslog.log"
    path.write_text(text, encoding="utf-8", newline="\n")
    seen = logfold.inspect_file(path, format="syslog")
    assert (seen.records, seen.unparsed) == (4, 0)
    assert [record.lines for record in seen.shown] == [2, 1, 1, 1]
    assert [record.time is not None for record in seen.shown] == [True, True, True, True]
    assert str(seen.shown[1].time) == "2018-08-14 12:30:02.203151+00:00"


def test_github_actions_joins_the_lines_of_a_multi_line_value(tmp_path: Path) -> None:
    text = (
        "﻿2026-10-14T17:48:10.9485011Z ##[group]Run astral-sh/setup-uv\n"
        "2026-10-14T17:48:10.9486835Z   enable-cache: auto\n"
        "2026-10-14T17:48:10.9487353Z   cache-dependency-glob: **/*requirements*.txt\n"
        "**/*requirements*.in\n"
        "**/pyproject.toml\n"
        "2026-10-14T17:48:10.9490000Z ##[endgroup]\n"
    )
    path = tmp_path / "job.txt"
    path.write_text(text, encoding="utf-8", newline="\n")
    seen = logfold.inspect_file(path, format="github-actions")
    assert (seen.records, seen.unparsed) == (4, 0)
    assert [record.lines for record in seen.shown] == [1, 1, 3, 1]


def test_a_line_in_another_encoding_is_not_lost(tmp_path: Path) -> None:
    lines = [
        b'1.2.3.4 - - [07/Dec/2016:11:05:07 +0100] "GET /caf\xe9 HTTP/1.1" 200 5',
        b'1.2.3.4 - - [07/Dec/2016:11:05:08 +0100] "GET /ok HTTP/1.1" 200 5',
    ]
    path = tmp_path / "latin1.log"
    path.write_bytes(b"\n".join(lines) + b"\n")
    result = logfold.analyze(path, format="nginx")
    assert (result.run.records, result.run.unparsed) == (2, 0)
    other = tmp_path / "app.log"
    other.write_bytes(b"2026-10-04 10:00:00 INFO caf\xe9 started\n2026-10-04 10:00:01 INFO ok\n")
    result = logfold.analyze(other, format="app")
    assert (result.run.records, result.run.unparsed) == (2, 0)
    seen = logfold.inspect_file(other, format="app")
    assert seen.shown[0].message == "caf\ufffd started"


def test_a_json_line_in_another_encoding_is_not_lost(tmp_path: Path) -> None:
    path = tmp_path / "a.jsonl"
    path.write_bytes(b'{"message": "caf\xe9 started", "level": "warn"}\n{"message": "ok"}\n')
    result = logfold.analyze(path, format="jsonl")
    assert (result.run.records, result.run.unparsed) == (2, 0)
