"""Grammars of valid lines for the built-in formats, and mutations of a whole log (used by the format fuzz tests).

``GRAMMARS`` maps the name of a format to a Hypothesis strategy of one line (no line break). ``mutated_log`` turns a
list of lines into the bytes of a log and damages it the way real logs are damaged: cut lines, CR LF, a byte order
mark, tabs, NUL, bytes that are not UTF-8, very long lines, blank lines, shuffled order and a last line without a line
break.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from hypothesis import strategies as st

WORDS = [
    "started",
    "failed",
    "user",
    "42",
    "10.0.0.1",
    "/api/v1/items",
    "é",
    "日本語",
    "x=1",
    "a b",
    "[x]",
    '"q"',
    "-",
    "::1",
]
LEVELS = ["TRACE", "DEBUG", "INFO", "WARN", "WARNING", "ERROR", "FATAL", "NOTICE", "LOG"]
MONTHS = ["Jan", "Feb", "Mar", "Oct", "Dec"]
ZONES = ["Z", "+00:00", "+0200", "-05:00", "+05:30", ""]
BASE = datetime(2026, 10, 4, 12, 0, 0)

text = st.lists(st.sampled_from(WORDS), min_size=0, max_size=8).map(" ".join)
moments = st.integers(-40_000_000, 40_000_000).map(lambda seconds: BASE + timedelta(seconds=seconds))
micros = st.integers(0, 999_999)
levels = st.sampled_from(LEVELS)
pids = st.integers(1, 99999)


@st.composite
def iso(draw: st.DrawFn, separator: str = "T", zone: bool = True, fraction: bool = True) -> str:
    moment = draw(moments)
    out = moment.strftime(f"%Y-%m-%d{separator}%H:%M:%S")
    if fraction and draw(st.booleans()):
        out += f"{draw(st.sampled_from(['.', ',']))}{draw(micros):06d}"[: draw(st.integers(2, 7))]
    return out + (draw(st.sampled_from(ZONES)) if zone else "")


@st.composite
def access(draw: st.DrawFn) -> str:
    moment = draw(moments)
    client = draw(st.sampled_from(["::1", "10.0.0.1", "10.0.0.2, 10.0.0.1", '"1.2.3.4, 5.6.7.8"', "unix:"]))
    host = draw(st.sampled_from(["", "example.com ", "vhost:443 "]))
    stamp = moment.strftime(f"%d/{draw(st.sampled_from(MONTHS))}/%Y:%H:%M:%S") + draw(
        st.sampled_from([" +0000", " +0200", " -0500"])
    )
    request = draw(st.sampled_from(['"GET / HTTP/1.1"', '"POST /a?b=1 HTTP/2"', '""', '"hello"']))
    status = draw(st.sampled_from([200, 404, 500, 400]))
    return f"{host}{client} - - [{stamp}] {request} {status} {draw(st.integers(0, 9999))}"


@st.composite
def nginx_error(draw: st.DrawFn) -> str:
    stamp = draw(moments).strftime("%Y/%m/%d %H:%M:%S")
    level = draw(st.sampled_from(["error", "warn", "notice", "crit"]))
    return f"{stamp} [{level}] {draw(pids)}#0: *{draw(pids)} {draw(text)}"


@st.composite
def haproxy(draw: st.DrawFn) -> str:
    stamp = (
        draw(moments).strftime(f"%d/{draw(st.sampled_from(MONTHS))}/%Y:%H:%M:%S") + f".{draw(st.integers(0, 999)):03d}"
    )
    prefix = draw(
        st.sampled_from(
            [
                "",
                "Oct  4 12:00:00 host haproxy[12]: ",
                "<134>1 2026-10-04T12:00:00+00:00 host haproxy 12 - - ",
                "2026-10-04T12:00:00+00:00 ",
            ]
        )
    )
    status = draw(st.sampled_from([200, 503]))
    return f"{prefix}10.0.0.1:{draw(st.integers(1, 65535))} [{stamp}] front back/srv 0/0/1/2/3 {status} {draw(text)}"


@st.composite
def postgresql(draw: st.DrawFn) -> str:
    stamp = draw(moments).strftime("%Y-%m-%d %H:%M:%S") + draw(
        st.sampled_from(["", f".{draw(st.integers(0, 999)):03d}"])
    )
    zone = draw(st.sampled_from([" UTC", " CEST", ""]))
    kind = draw(st.sampled_from(["LOG", "ERROR", "WARNING", "FATAL", "DETAIL", "STATEMENT", "HINT"]))
    return f"{stamp}{zone} [{draw(pids)}] {kind}:  {draw(text)}"


@st.composite
def postgresql_csv(draw: st.DrawFn) -> str:
    stamp = draw(moments).strftime("%Y-%m-%d %H:%M:%S.000 UTC")
    message = draw(text).replace('"', '""')
    severity = draw(st.sampled_from(["LOG", "ERROR"]))
    head = f'{stamp},"postgres","db",{draw(pids)},"1.2.3.4:5",abc.1,1,"idle",{stamp},3/0,0'
    return f'{head},{severity},00000,"{message}",,,,,,,,,"psql"'


@st.composite
def log4j(draw: st.DrawFn) -> str:
    stamp = draw(moments).strftime("%Y-%m-%d %H:%M:%S") + f",{draw(st.integers(0, 999)):03d}"
    level = draw(st.sampled_from(["TRACE", "DEBUG", "INFO ", "WARN ", "ERROR", "FATAL"]))
    thread = draw(st.sampled_from(["main", "pool-1-thread-2", "My Thread"]))
    return f"{stamp} {level} [{thread}] com.example.App - {draw(text)}"


@st.composite
def docker_json(draw: st.DrawFn) -> str:
    entry: dict[str, object] = {"log": draw(text) + draw(st.sampled_from(["\n", "\n", "\r\n", ""]))}
    if draw(st.booleans()):
        entry["stream"] = draw(st.sampled_from(["stdout", "stderr"]))
    if draw(st.booleans()):
        entry["time"] = draw(moments).strftime("%Y-%m-%dT%H:%M:%S.") + f"{draw(micros):06d}123Z"
    return json.dumps(entry, ensure_ascii=draw(st.booleans()))


@st.composite
def github_actions(draw: st.DrawFn) -> str:
    stamp = draw(moments).strftime("%Y-%m-%dT%H:%M:%S") + f".{draw(micros):06d}0Z"
    return f"{stamp} {draw(st.sampled_from(['', '##[error]', '##[warning]', '##[group]', '##[debug]']))}{draw(text)}"


@st.composite
def k8s(draw: st.DrawFn) -> str:
    stamp = draw(moments).strftime("%Y-%m-%dT%H:%M:%S.") + f"{draw(micros):06d}000Z"
    return f"{stamp} {draw(st.sampled_from(['stdout', 'stderr']))} {draw(st.sampled_from(['F', 'P']))} {draw(text)}"


@st.composite
def logfmt(draw: st.DrawFn) -> str:
    stamp = draw(iso(zone=True))
    extra = " ".join(
        f"k{i}={draw(st.sampled_from(['1', 'a', 'http.go:9', '']))}" for i in range(draw(st.integers(0, 3)))
    )
    key = draw(st.sampled_from(["ts", "time"]))
    level = draw(st.sampled_from(["level", "lvl"]))
    quote = draw(st.sampled_from(["", '"']))
    value = draw(st.sampled_from(["info", "warn", "error", "debug"]))
    line = f'{key}={quote}{stamp}{quote} {extra} {level}={value} msg="{draw(text)}"'
    return line.replace("  ", " ")


@st.composite
def serilog_clef(draw: st.DrawFn) -> str:
    entry: dict[str, object] = {"@t": draw(iso()), "@m": draw(text)}
    if draw(st.booleans()):
        entry["@l"] = draw(st.sampled_from(["Information", "Warning", "Error", "Debug", "Fatal"]))
    return json.dumps(entry)


@st.composite
def jsonl(draw: st.DrawFn) -> str:
    entry: dict[str, object] = {draw(st.sampled_from(["message", "msg", "log"])): draw(text)}
    if draw(st.booleans()):
        entry[draw(st.sampled_from(["timestamp", "time", "ts", "@timestamp", "timeMillis"]))] = draw(
            st.one_of(iso(), st.integers(0, 2_000_000_000_000), st.integers(0, 2_000_000_000))
        )
    if draw(st.booleans()):
        entry[draw(st.sampled_from(["level", "severity", "lvl", "log.level"]))] = draw(levels)
    return json.dumps(entry)


@st.composite
def journald(draw: st.DrawFn) -> str:
    entry = {
        "MESSAGE": draw(text),
        "PRIORITY": str(draw(st.integers(0, 7))),
        "__REALTIME_TIMESTAMP": str(draw(st.integers(0, 2_000_000_000_000_000))),
    }
    return json.dumps(entry)


@st.composite
def syslog(draw: st.DrawFn) -> str:
    classic = draw(moments).strftime("%b %e %H:%M:%S")
    stamp = draw(st.sampled_from([classic, draw(iso(zone=False))]))
    return f"{stamp} host prog[{draw(pids)}]: {draw(text)}"


@st.composite
def app(draw: st.DrawFn) -> str:
    stamp = draw(iso(separator=draw(st.sampled_from(["T", " "]))))
    thread = draw(st.sampled_from(["", "[main] ", "[worker-1] "]))
    return f"{stamp} {thread}{draw(st.sampled_from(['INFO', 'ERROR', 'WARN', 'DEBUG']))} {draw(text)}"


GRAMMARS: dict[str, st.SearchStrategy[str]] = {
    "nginx": access(),
    "apache": access(),
    "nginx-error": nginx_error(),
    "haproxy": haproxy(),
    "postgresql": postgresql(),
    "postgresql-csv": postgresql_csv(),
    "log4j": log4j(),
    "docker-json": docker_json(),
    "github-actions": github_actions(),
    "k8s": k8s(),
    "logfmt": logfmt(),
    "serilog-clef": serilog_clef(),
    "jsonl": jsonl(),
    "journald": journald(),
    "syslog": syslog(),
    "app": app(),
    "plain": text,
}

NOISE = [b"\x00", b"\xff\xfe", b"\xc3", b"\t", b" ", b"\x1b[31m", b"\xef\xbb\xbf", b'"', b"\\", b"{", b"[", b"\r"]


@st.composite
def damaged(draw: st.DrawFn, line: str) -> bytes:
    """Damage one line: cut it, put noise into it or make it very long."""
    data = line.encode("utf-8")
    action = draw(st.sampled_from(["keep", "keep", "keep", "cut", "noise", "long", "empty"]))
    if action == "cut" and data:
        return data[: draw(st.integers(0, len(data)))]
    if action == "noise":
        at = draw(st.integers(0, len(data)))
        return data[:at] + draw(st.sampled_from(NOISE)) + data[at:]
    if action == "long":
        return data + b"x" * draw(st.sampled_from([5_000, 70_000]))
    if action == "empty":
        return b""
    return data


@st.composite
def mutated_log(draw: st.DrawFn, grammar: st.SearchStrategy[str], max_lines: int = 40) -> bytes:
    """Return the bytes of a log of lines of ``grammar`` that has been damaged in several of the usual ways."""
    lines = draw(st.lists(grammar, min_size=0, max_size=max_lines))
    if draw(st.booleans()):
        draw(st.randoms(use_true_random=False)).shuffle(lines)
    parts = [draw(damaged(line)) for line in lines]
    eol = draw(st.sampled_from([b"\n", b"\n", b"\r\n", b"\r"]))
    body = eol.join(parts)
    if draw(st.sampled_from([True, True, False])):
        body += eol
    if draw(st.booleans()):
        body = b"\xef\xbb\xbf" + body
    if draw(st.booleans()):
        body = b"banner of the program starting\n\n" + body
    return body
