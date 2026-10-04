from __future__ import annotations

import json
from pathlib import Path

import pytest

import logfold
from corpora import CORPORA, app_lines, write
from logfold import FormatError
from logfold.ext.formats import JsonFormat, PlainFormat, RegexFormat, with_multiline
from logfold.formats import BUILTIN_FORMATS, detect_format, regex_format_from_pattern, resolve_format

SAMPLES = {
    "nginx": '10.0.0.1 - - [04/Oct/2026:12:00:00 +0300] "GET /api/items/7 HTTP/1.1" 200 512 "-" "curl/8"',
    "apache": '10.0.0.1 - bob [04/Oct/2026:12:00:00 +0000] "POST /login HTTP/1.1" 302 0',
    "nginx-error": "2026/10/04 12:00:00 [error] 12#12: *3 open() failed",
    "syslog": "Oct  4 12:00:00 host sshd[123]: Accepted publickey for bob",
    "k8s": "2026-10-04T12:00:00.123456789Z stdout F request served",
    "app": "2026-10-04 12:00:00,123 [main] WARNING  disk almost full",
    "jsonl": '{"ts": "2026-10-04T12:00:00Z", "level": "info", "msg": "hello"}',
    "journald": '{"__REALTIME_TIMESTAMP": "1790000000000000", "PRIORITY": "3", "MESSAGE": "unit failed"}',
}


@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_builtin_formats_parse_their_samples(tmp_path: Path, name: str) -> None:
    path = tmp_path / "one.log"
    path.write_text(SAMPLES[name] + "\n", encoding="utf-8")
    result = logfold.analyze(str(path), format=name, engine="python")
    assert result.run.records == 1, name
    template = result.templates[0]
    if name not in ("nginx-error", "app", "jsonl", "journald") or name == "app":
        pass
    if name in ("nginx", "apache", "nginx-error", "syslog", "k8s", "app", "jsonl", "journald"):
        assert template.first_seen is not None, name


def test_level_extraction(tmp_path: Path) -> None:
    path = tmp_path / "levels.log"
    path.write_text(SAMPLES["app"] + "\n" + SAMPLES["nginx-error"] + "\n", encoding="utf-8")
    app = logfold.analyze(str(path), format="app", engine="python")
    assert [t.level for t in app.templates if t.count] == ["WARN"]
    err = logfold.analyze(str(path), format="nginx-error", engine="python")
    assert err.templates[0].level == "ERROR"


def test_journald_priority_maps_to_levels(tmp_path: Path) -> None:
    path = tmp_path / "j.log"
    rows = [{"__REALTIME_TIMESTAMP": "1790000000000000", "PRIORITY": p, "MESSAGE": f"msg {p}"} for p in "3467"]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    result = logfold.analyze(str(path), format="journald", sim_th=1.0, engine="python")
    assert result.templates[0].levels == {"ERROR": 1, "WARN": 1, "INFO": 1, "DEBUG": 1}
    assert result.templates[0].level == "ERROR"


@pytest.mark.parametrize("name", ["app", "nginx", "syslog", "jsonl", "journald"])
def test_auto_detection(corpus_dir: Path, name: str) -> None:
    detection = detect_format([str(corpus_dir / f"{name}.log")])
    assert detection.spec.name == name
    assert detection.confidence >= 0.8


def test_auto_detection_flags_multiline(corpus_dir: Path) -> None:
    resolved = resolve_format("auto", [str(corpus_dir / "multiline.log")])
    assert resolved.spec.name == "app"
    assert resolved.multiline_auto is True
    assert resolved.spec.multiline is True
    explicit = resolve_format("auto", [str(corpus_dir / "multiline.log")], multiline=False)
    assert explicit.spec.multiline is False
    assert explicit.multiline_auto is False


def test_auto_detection_fails_loudly_on_unstructured_text(tmp_path: Path) -> None:
    path = tmp_path / "free.txt"
    write(path, CORPORA["unicode"][0](200))
    with pytest.raises(FormatError, match="could not detect"):
        logfold.analyze(str(path))


def test_auto_detection_of_empty_file_is_plain(tmp_path: Path) -> None:
    path = tmp_path / "empty.log"
    path.write_text("", encoding="utf-8")
    result = logfold.analyze(str(path), engine="python")
    assert result.run.records == 0
    assert any("no records" in w for w in result.warnings)


def test_regex_format_picks_conventional_groups() -> None:
    spec = regex_format_from_pattern(r"^(?P<ts>\S+) (?P<level>\w+) (?P<message>.*)$")
    assert (spec.message_group, spec.time_group, spec.level_group) == ("message", "ts", "level")
    with pytest.raises(FormatError):
        regex_format_from_pattern("(unclosed")


def test_regex_format_validation() -> None:
    with pytest.raises(FormatError):
        RegexFormat(pattern="(?P<a>x)", message_group="missing")
    with pytest.raises(FormatError):
        PlainFormat(multiline=True)
    with pytest.raises(FormatError):
        JsonFormat(message_keys=())
    with pytest.raises(FormatError):
        JsonFormat(multiline=True)
    with pytest.raises(FormatError):
        with_multiline(JsonFormat(), True)


def test_custom_regex_format_end_to_end(tmp_path: Path) -> None:
    path = tmp_path / "custom.log"
    path.write_text("[2026-10-04 12:00:00] <warn> disk 91% full\n[2026-10-04 12:00:01] <warn> disk 92% full\n")
    spec = RegexFormat(
        pattern=r"^\[(?P<ts>[^\]]+)\] <(?P<lvl>\w+)> (?P<msg>.*)$",
        message_group="msg",
        time_group="ts",
        level_group="lvl",
    )
    for engine in ("python", "auto"):
        result = logfold.analyze(str(path), format=spec, engine=engine)
        assert [(t.text, t.count, t.level) for t in result.templates] == [("disk <NUM>% full", 2, "WARN")]


def test_bad_timestamp_format_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "a.log"
    path.write_text("x\n", encoding="utf-8")
    spec = RegexFormat(pattern=r"(?P<ts>\d+)", time_group="ts", ts_format="%Q")
    for engine in ("python", "auto"):
        with pytest.raises(FormatError):
            logfold.analyze(str(path), format=spec, engine=engine)


def test_builtin_names_are_registered() -> None:
    from logfold.ext import format_names

    assert set(BUILTIN_FORMATS) <= set(format_names())


def test_app_format_handles_python_style_logs(tmp_path: Path) -> None:
    path = tmp_path / "py.log"
    write(path, app_lines(100))
    assert logfold.analyze(str(path), format="auto").meta.format == "app"
