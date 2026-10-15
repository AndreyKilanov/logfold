"""The ``log4j`` format against real Java logging libraries (used by ``formats.py``).

A Java program writes numbered events of every level through log4j2, logback and log4j 1.x (reload4j): plain events, an
empty message, messages of several lines, an exception with a cause chain and a suppressed exception, a long message, MDC
values and several thread names. Next to the log it writes its own record of the events (``java/Scenario.java``): the
level, the first line of the message, how many lines the event added to the file (counted from the growth of the file, so
no parser decides the boundaries) and the wall-clock time just before and after the call.

Each pattern is read with ``-f "log4j:<pattern>"`` and compared record by record: the level, the first line of the
message, the number of lines and a time between the two clock readings.
"""

from __future__ import annotations

import argparse
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from formats import docker
from keep_logs import keep as keep_log

import logfold

JAVA_IMAGES = {17: "eclipse-temurin:17.0.16_8-jdk-alpine", 21: "eclipse-temurin:21-jdk-alpine"}
MAVEN = "https://repo1.maven.org/maven2"
JARS = {
    "log4j-api-2.25.2.jar": ("org/apache/logging/log4j/log4j-api/2.25.2", "9fd66c9fe0bea06fa9666c147989a46cafaa92b4a88753697d3945cc43338cbb"),
    "log4j-core-2.25.2.jar": ("org/apache/logging/log4j/log4j-core/2.25.2", "e50db7701430ff907981850ef527a41d51a53dd0017f53a0860afcbab8570277"),
    "logback-classic-1.5.18.jar": ("ch/qos/logback/logback-classic/1.5.18", "3e1533d0321f8815eef46750aee0111b41554f9a4644c3c4d2d404744b09f60f"),
    "logback-core-1.5.18.jar": ("ch/qos/logback/logback-core/1.5.18", "85139e7b57b464f8e5e36326dd81317648bed199ccc4f98cd42585f8d7571027"),
    "slf4j-api-2.0.17.jar": ("org/slf4j/slf4j-api/2.0.17", "7b751d952061954d5abfed7181c1f645d336091b679891591d63329c622eb832"),
    "reload4j-1.2.25.jar": ("ch/qos/reload4j/reload4j/1.2.25", "e71115175c4b080cf51dd72097165ea001ff9fafdc4f79d88049d0b1ecca979c"),
}  # fmt: skip
CLASSPATH = {
    "log4j2": ["log4j-api-2.25.2.jar", "log4j-core-2.25.2.jar"],
    "logback": ["logback-classic-1.5.18.jar", "logback-core-1.5.18.jar", "slf4j-api-2.0.17.jar"],
    "log4j1": ["reload4j-1.2.25.jar"],
}
EMITTER = {"log4j2": "Log4j2Emitter", "logback": "LogbackEmitter", "log4j1": "Log4j1Emitter"}
LIBRARY_VERSION = {"log4j2": "log4j2 2.25.2", "logback": "logback 1.5.18", "log4j1": "reload4j 1.2.25 (log4j 1.x)"}
SOURCES = Path(__file__).parent / "java"
WORK = "/work"
STAMP = "%Y-%m-%dT%H:%M:%S.%f"
SINGLE_LINE_WITH_EXCEPTION = ("exception", "bracket")
"""The events whose one-line message is followed by an exception: ``%m%ex`` of log4j2 glues the two on one line."""
MAX_SHOWN = 3


@dataclass
class JavaCase:
    """One library with one conversion pattern."""

    library: str
    pattern: str
    java: int = 21
    timezone: str = "UTC"
    time_only: bool = False
    glued: bool = False

    def label(self) -> str:
        """Return a short name for the table."""
        zone = "" if self.timezone == "UTC" else f", {self.timezone}"
        return f"{LIBRARY_VERSION[self.library]}, Java {self.java}{zone}: `{self.pattern}`"


@dataclass
class JavaOutcome:
    """What one case found."""

    case: JavaCase
    events: int = 0
    lines: int = 0
    problems: list[str] = field(default_factory=list)
    auto: str = ""


@dataclass
class Event:
    """One line of the record that the Java program wrote."""

    number: int
    level: str
    kind: str
    message: str
    lines: int
    before: datetime
    after: datetime
    thrown: str


def configuration(case: JavaCase, log: str) -> tuple[str, str, list[str]]:
    """Return the name and text of the configuration file and the JVM options that point at it."""
    folder = f"{WORK}/run/{log}"
    pattern = escape(case.pattern, {'"': "&quot;"})
    if case.library == "log4j2":
        text = (
            '<Configuration status="WARN"><Appenders>'
            f'<File name="F" fileName="{folder}/app.log" append="false" immediateFlush="true">'
            f'<PatternLayout pattern="{pattern}"/></File></Appenders>'
            '<Loggers><Root level="all"><AppenderRef ref="F"/></Root></Loggers></Configuration>'
        )
        return "log4j2.xml", text, [f"-Dlog4j2.configurationFile={folder}/log4j2.xml"]
    if case.library == "logback":
        text = (
            '<configuration><appender name="F" class="ch.qos.logback.core.FileAppender">'
            f"<file>{folder}/app.log</file><append>false</append><immediateFlush>true</immediateFlush>"
            f"<encoder><pattern>{pattern}</pattern></encoder></appender>"
            '<root level="ALL"><appender-ref ref="F"/></root></configuration>'
        )
        return "logback.xml", text, [f"-Dlogback.configurationFile={folder}/logback.xml"]
    text = (
        "log4j.rootLogger=ALL, F\n"
        "log4j.appender.F=org.apache.log4j.FileAppender\n"
        f"log4j.appender.F.File={folder}/app.log\n"
        "log4j.appender.F.Append=false\n"
        "log4j.appender.F.layout=org.apache.log4j.PatternLayout\n"
        f"log4j.appender.F.layout.ConversionPattern={case.pattern}\n"
    )
    return "log4j.properties", text, [f"-Dlog4j.configuration=file:{folder}/log4j.properties"]


@contextmanager
def toolbox(java: int) -> Iterator[str]:
    """Start a JDK container with the pinned libraries downloaded and the emitters compiled; remove it at the end."""
    name = f"logfold-validate-java{java}"
    docker("rm", "-f", name, check=False)
    docker("run", "-d", "--name", name, JAVA_IMAGES[java], "sleep", "3600")
    try:
        docker("exec", name, "mkdir", "-p", f"{WORK}/jars", f"{WORK}/classes", f"{WORK}/run")
        for jar, (path, digest) in JARS.items():
            script = f"wget -q -O {WORK}/jars/{jar} {MAVEN}/{path}/{jar} && echo '{digest}  {WORK}/jars/{jar}' | sha256sum -c -"
            docker("exec", name, "sh", "-c", script)
        docker("cp", str(SOURCES), f"{name}:{WORK}/src")
        compiled = docker(
            "exec", name, "sh", "-c", f"javac -cp '{WORK}/jars/*' -d {WORK}/classes {WORK}/src/*.java", check=False
        )
        if compiled.returncode:
            raise RuntimeError(f"javac failed: {compiled.stderr[-800:]}")
        yield name
    finally:
        docker("rm", "-f", name, check=False)


def run_emitter(name: str, case: JavaCase, index: int, rounds: int, scratch: Path) -> tuple[Path, Path, str]:
    """Run the Java program for one case; return the log file, the record of the program and its console output."""
    log = f"case{index}"
    file_name, text, options = configuration(case, log)
    docker("exec", name, "mkdir", "-p", f"{WORK}/run/{log}")
    local = scratch / file_name
    local.write_text(text, encoding="utf-8", newline="\n")
    docker("cp", str(local), f"{name}:{WORK}/run/{log}/{file_name}")
    classpath = ":".join([f"{WORK}/classes", *(f"{WORK}/jars/{jar}" for jar in CLASSPATH[case.library])])
    folder = f"{WORK}/run/{log}"
    done = docker(
        "exec",
        name,
        "java",
        f"-Duser.timezone={case.timezone}",
        "-Dfile.encoding=UTF-8",
        *options,
        "-cp",
        classpath,
        EMITTER[case.library],
        f"{folder}/app.log",
        f"{folder}/oracle.tsv",
        str(rounds),
        check=False,
    )
    if done.returncode:
        raise RuntimeError(f"{case.label()}: the Java program failed: {(done.stdout + done.stderr)[-800:]}")
    paths = (scratch / f"{log}.log", scratch / f"{log}.tsv")
    docker("cp", f"{name}:{folder}/app.log", str(paths[0]))
    docker("cp", f"{name}:{folder}/oracle.tsv", str(paths[1]))
    return paths[0], paths[1], done.stdout + done.stderr


def read_events(path: Path) -> list[Event]:
    """Read the record that the Java program wrote."""
    events: list[Event] = []
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line:
            continue
        number, level, kind, message, lines, before, after, thrown = line.split("\t")
        events.append(
            Event(
                int(number),
                level,
                kind,
                message,
                int(lines),
                datetime.strptime(before, STAMP),
                datetime.strptime(after, STAMP),
                thrown,
            )
        )
    return events


def first_line(text: str) -> str:
    """Return the first line of a message."""
    return text.split("\n", 1)[0]


def compare(case: JavaCase, log: Path, events: list[Event], outcome: JavaOutcome) -> None:
    """Compare what logfold reads from the log with the record of the program, event by event."""
    problems = outcome.problems
    text = log.read_bytes().decode("utf-8")
    outcome.events, outcome.lines = len(events), sum(1 for line in text.splitlines() if line.strip())
    logged = sum(event.lines for event in events)
    if logged != outcome.lines:
        problems.append(f"the events add up to {logged} lines, the file has {outcome.lines}: the oracle is wrong")
        return
    try:
        seen = logfold.inspect_file(log, format=f"log4j:{case.pattern}", sample_lines=10_000_000, limit=10_000_000)
    except logfold.FormatError as error:
        problems.append(f"the pattern was refused: {str(error).splitlines()[0][:160]}")
        return
    if seen.records != len(events):
        problems.append(f"{seen.records} records, the program logged {len(events)} events")
    if seen.unparsed:
        problems.append(f"{seen.unparsed} lines were not parsed")
    wrong: dict[str, list[str]] = {"level": [], "message": [], "lines": [], "time": []}
    for event, record in zip(events, seen.shown, strict=False):
        who = f"event {event.number} {event.kind}"
        if record.level != event.level:
            wrong["level"].append(f"{who}: level {record.level}, logged {event.level}")
        glued = case.glued and event.kind in SINGLE_LINE_WITH_EXCEPTION
        expected = event.message + event.thrown if glued else event.message
        if first_line(record.message) != expected:
            wrong["message"].append(f"{who}: message {first_line(record.message)[:50]!r}, logged {expected[:50]!r}")
        if record.lines != event.lines:
            wrong["lines"].append(f"{who}: {record.lines} lines, the file grew by {event.lines}")
        if not time_fits(case, record.time, event):
            wrong["time"].append(f"{who}: time {record.time}, the call was between {event.before} and {event.after}")
    for kind, found in wrong.items():
        problems.extend(found[:MAX_SHOWN])
        if len(found) > MAX_SHOWN:
            problems.append(f"{len(found)} events differ in {kind}")


def time_fits(case: JavaCase, moment: datetime | None, event: Event) -> bool:
    """Tell whether the time of a record lies between the clock readings taken around the call."""
    if moment is None:
        return False
    moment = moment.replace(tzinfo=None)
    if case.time_only:
        return event.before.time() <= moment.time() <= event.after.time()
    return event.before <= moment <= event.after


def run_case(name: str, case: JavaCase, index: int, rounds: int) -> JavaOutcome:
    """Run one library with one pattern and compare what logfold reads with what the program logged."""
    outcome = JavaOutcome(case)
    with tempfile.TemporaryDirectory() as folder:
        log, oracle, console = run_emitter(name, case, index, rounds, Path(folder))
        events = read_events(oracle)
        keep_log(log, "log4j", f"{index}-{name}", f"log4j:{case.pattern}")
        compare(case, log, events, outcome)
        try:
            outcome.auto = logfold.analyze(log, format="auto").meta.format
        except logfold.FormatError:
            outcome.auto = "refused"
        if outcome.problems:
            keep = Path(tempfile.gettempdir()) / f"logfold-validate-java-{index}.log"
            keep.write_bytes(log.read_bytes())
            outcome.problems.append(
                f"log kept in {keep}" + (f", console: {console[-200:]!r}" if console.strip() else "")
            )
    return outcome


DEFAULT = "%d{ISO8601} %-5p [%t] %c - %m%n"
SPRING = "%d{yyyy-MM-dd'T'HH:mm:ss.SSSXXX} %5p 1 --- [%15.15t] %-40.40logger{39} : %m%n%ex"


def cases() -> list[JavaCase]:
    """Return the libraries and patterns to check: the common layouts of each library, plus other Java versions and zones."""
    log4j2 = [
        DEFAULT,
        "%d{yyyy-MM-dd HH:mm:ss.SSS} [%t] %-5level %logger{36} - %msg%n",
        "%d{ISO8601} %-5p [%t] %c{1.} (%X{requestId}) - %m%n",
        "%d{DATE} [%t] %-5p %c{1} - %m%n",
        SPRING,
    ]
    logback = [
        "%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n",
        DEFAULT,
        "%d [%t] %-5p %c - %m%n",
        "%d{ISO8601} [%t] %-5level %logger{20} [%X{requestId:-none}] - %msg%n",
        SPRING,
    ]
    log4j1 = [
        DEFAULT,
        "%d [%t] %-5p %c - %m%n",
        "%d{ISO8601} %-5p %c{1}:%L - %m%n",
        "%d{dd MMM yyyy HH:mm:ss,SSS} %-5p [%t] %c - %m%n",
    ]
    chosen = [JavaCase("log4j2", pattern) for pattern in log4j2]
    chosen += [JavaCase("log4j2", "%d{HH:mm:ss.SSS} [%t] %-5level %logger{36} - %msg%n", time_only=True)]
    chosen += [JavaCase("log4j2", "%d{ABSOLUTE} [%t] %-5p %c{1} - %m%n", time_only=True)]
    chosen += [
        JavaCase("log4j2", "%d{DEFAULT} %p %c{1.} [%t] %m%n%ex"),
        JavaCase("log4j2", "%d{DEFAULT} %p [%t] %m%ex%n", glued=True),
    ]
    chosen += [JavaCase("logback", pattern) for pattern in logback]
    chosen += [JavaCase("logback", "%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n", time_only=True)]
    chosen += [JavaCase("log4j1", pattern) for pattern in log4j1]
    chosen += [JavaCase("log4j2", DEFAULT, java=17), JavaCase("logback", DEFAULT, java=17)]
    chosen += [
        JavaCase("log4j2", DEFAULT, timezone="Asia/Kolkata"),
        JavaCase("logback", DEFAULT, timezone="America/New_York"),
    ]
    return chosen


def run_java_cases(args: argparse.Namespace) -> int:
    """Run the Java cases, print their table and return the number that failed."""
    chosen = [case for case in cases() if args.only is None or args.only in case.label()]
    print("| library, pattern | events | lines | `-f auto` | result |")
    print("|---|---:|---:|---|---|")
    failed = 0
    index = 0
    for java in sorted({case.java for case in chosen}):
        with toolbox(java) as name:
            for case in (c for c in chosen if c.java == java):
                outcome = run_case(name, case, index, args.rounds)
                index += 1
                failed += bool(outcome.problems)
                verdict = "all numbers match" if not outcome.problems else "; ".join(outcome.problems)
                print(
                    f"| {case.label()} | {outcome.events} | {outcome.lines} | {outcome.auto} | {verdict} |", flush=True
                )
    return failed
