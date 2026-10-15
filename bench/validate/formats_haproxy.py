"""The ``haproxy`` format against real HAProxy 2.8, 3.0 and 3.2 (used by ``formats.py``).

HAProxy answers numbered requests itself (``http-request return`` and ``deny``, a backend whose only server is down) and
logs to its standard output in each of the forms of ``log stdout format``. The requests come from a second container
that shares the network of the first, so no other connection (for example a probe of a published port) reaches the log.
The expected result is what was sent: for every request the frontend, the backend, the status, the method and the path.
They are read back from the records with a pattern of this script, not of logfold.
"""

from __future__ import annotations

import re
import tempfile
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from formats import docker
from keep_logs import keep

import logfold

HAPROXY_IMAGES = {"2.8": "haproxy:2.8.30", "3.0": "haproxy:3.0.29", "3.2": "haproxy:3.2.25"}
EMITTER_IMAGE = "python:3.13.7-alpine"
LOG_FORMATS = ("raw", "short", "iso", "rfc3164", "rfc5424")
CONFIG = """global
    log stdout format {form} local0
defaults
    log global
    mode http
    option {http_log}
    retries 0
    timeout connect 2s
    timeout client 5s
    timeout server 5s
frontend fe_http
    bind *:8080
    http-request return status 200 content-type text/plain string ok if {{ path_beg /ok }}
    http-request deny deny_status 403 if {{ path_beg /denied }}
    default_backend be_app
backend be_app
    server srv1 127.0.0.1:1
frontend fe_tcp
    mode tcp
    option tcplog
    bind *:8081
    default_backend be_tcp
backend be_tcp
    mode tcp
    server srv_tcp 127.0.0.1:1
"""
EMITTER = """
import http.client, socket, sys
rounds = int(sys.argv[1])
for number in range(1, rounds + 1):
    for method, path in (("GET", f"/ok/{number}"), ("POST", f"/ok/{number}"), ("GET", f"/denied/{number}"),
                         ("HEAD", f"/down/{number}"), ("GET", f"/down/{number}?q=" + "x" * 1500)):
        connection = http.client.HTTPConnection("127.0.0.1", 8080, timeout=10)
        connection.request(method, path, body="data" if method == "POST" else None, headers={"Connection": "close"})
        connection.getresponse().read()
        connection.close()
    for _ in range(2):
        socket.create_connection(("127.0.0.1", 8081)).close()
    garbage = socket.create_connection(("127.0.0.1", 8080))
    garbage.sendall(b"\\x16\\x03\\x01 not http\\r\\n\\r\\n")
    garbage.recv(1000)
    garbage.close()
"""
HTTP_LINE = re.compile(r'^(?P<fe>\S+) (?P<be>[^/\s]+)/(?P<srv>\S+) \S+ (?P<status>\d{3}) \d+ .* "(?P<request>[^"]*)"?$')
TCP_LINE = re.compile(r"^(?P<fe>\S+) (?P<be>[^/\s]+)/(?P<srv>\S+) \d+/-?\d+/-?\d+ \d+ \S+ \d+/\d+/\d+/\d+/\d+ \d+/\d+$")
Request = tuple[str, str, str, str, str]
"""``(frontend, backend, status or "tcp", method, path)``."""


@dataclass
class HaproxyCase:
    """One HAProxy version, log line form and request log option."""

    version: str
    form: str
    http_log: str = "httplog"

    def label(self) -> str:
        """Return a short name for the table."""
        return f"{self.version} {self.form}" + ("" if self.http_log == "httplog" else f" {self.http_log}")


@dataclass
class HaproxyOutcome:
    """What one HAProxy case found."""

    case: HaproxyCase
    requests: int = 0
    lines: int = 0
    problems: list[str] = field(default_factory=list)
    note: str = ""


def expected_requests(rounds: int) -> Counter[Request]:
    """Return the requests that the emitter sends, as the log must show them."""
    expected: Counter[Request] = Counter()
    for number in range(1, rounds + 1):
        expected[("fe_http", "fe_http", "200", "GET", f"/ok/{number}")] += 1
        expected[("fe_http", "fe_http", "200", "POST", f"/ok/{number}")] += 1
        expected[("fe_http", "fe_http", "403", "GET", f"/denied/{number}")] += 1
        expected[("fe_http", "be_app", "503", "HEAD", f"/down/{number}")] += 1
        expected[("fe_http", "be_app", "503", "GET", f"/down/{number}")] += 1
        expected[("fe_tcp", "be_tcp", "tcp", "", "")] += 2
        expected[("fe_http", "fe_http", "400", "", "<BADREQ>")] += 1
    return expected


def read_request(message: str) -> Request | None:
    """Read the frontend, backend, status, method and path from the message of a record."""
    tcp = TCP_LINE.match(message)
    if tcp:
        return tcp["fe"], tcp["be"], "tcp", "", ""
    http = HTTP_LINE.match(message)
    if not http:
        return None
    request = http["request"]
    if request == "<BADREQ>":
        return http["fe"], http["be"], http["status"], "", request
    method, path = request.split(" ")[:2]
    return http["fe"], http["be"], http["status"], method, path.split("?")[0]


def logged_lines(text: str) -> list[str]:
    """Return the non-blank lines of the log."""
    return [line for line in text.splitlines() if line.strip()]


def run_haproxy(case: HaproxyCase, index: int, rounds: int) -> HaproxyOutcome:
    """Run HAProxy and the emitter, then compare what logfold reads with what was sent."""
    outcome = HaproxyOutcome(case)
    name = f"logfold-validate-haproxy-{index}"
    docker("rm", "-f", name, check=False)
    with tempfile.TemporaryDirectory() as folder:
        config = Path(folder) / "haproxy.cfg"
        config.write_text(CONFIG.format(form=case.form, http_log=case.http_log), encoding="utf-8", newline="\n")
        docker("create", "--name", name, HAPROXY_IMAGES[case.version])
        try:
            docker("cp", str(config), f"{name}:/usr/local/etc/haproxy/haproxy.cfg")
            docker("start", name)
            time.sleep(2)
            started = datetime.utcnow()
            docker("run", "--rm", "--network", f"container:{name}", EMITTER_IMAGE, "python", "-c", EMITTER, str(rounds))
            time.sleep(1)
            docker("stop", "-t", "10", name)
            ended = datetime.utcnow()
            text = docker("logs", name).stdout
        finally:
            docker("rm", "-f", name, check=False)
        log = Path(folder) / "haproxy.log"
        log.write_text(text, encoding="utf-8", newline="\n")
        keep(log, "haproxy", f"{index}-{case.label()}")
        check_log(case, log, rounds, (started, ended), outcome)
    return outcome


def check_log(
    case: HaproxyCase, log: Path, rounds: int, window: tuple[datetime, datetime], outcome: HaproxyOutcome
) -> None:
    """Compare the log with the requests that were sent."""
    problems = outcome.problems
    expected = expected_requests(rounds)
    outcome.requests = sum(expected.values())
    seen = logfold.inspect_file(log, format="haproxy", sample_lines=10_000_000, limit=10_000_000)
    outcome.lines = seen.lines + seen.unparsed
    if case.http_log != "httplog":
        outcome.note = (
            f"not supported (httplog and tcplog are): {seen.records} of {outcome.requests} request lines read"
        )
        return
    if seen.records != outcome.requests:
        problems.append(f"{seen.records} records, {outcome.requests} requests were sent")
    got = Counter(read_request(record.message) for record in seen.shown)
    for found in list((got - expected).elements())[:2]:
        problems.append(f"read {found!r}, nothing like it was sent")
    for wanted in list((expected - got).elements())[:2]:
        problems.append(f"sent {wanted!r}, not read like that")
    noise = [line for line in logged_lines(log.read_text(encoding="utf-8")) if not is_request_line(line)]
    if seen.unparsed != len(noise):
        problems.append(f"{seen.unparsed} lines not parsed, {len(noise)} are not request lines")
    stray = [line for line in noise if " stopped (cumulated conns" not in line]
    if stray:
        problems.append(f"{len(stray)} unexpected lines, the first: {stray[0][:80]!r}")
    first, last = (moment.replace(tzinfo=None) if moment else None for moment in (seen.first_time, seen.last_time))
    margin = timedelta(seconds=60)
    if first is None or last is None or first < window[0] - margin or last > window[1] + margin:
        problems.append(f"time range {first} to {last} is outside the run {window[0]} to {window[1]}")


def is_request_line(line: str) -> bool:
    """Tell, by a pattern of this script, whether a log line is the line of a request or a connection.

    Every such line holds the accept date, ``[14/Oct/2026:19:20:27.955]`` (or ``[14/Oct/2026:19:21:23 +0000]`` in CLF).
    """
    return bool(re.search(r"\[\d{2}/\w{3}/\d{4}:\d{2}:\d{2}:\d{2}[^\]]*\]", line))
