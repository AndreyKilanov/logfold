"""Check the pipeline reporters with the real tools that read their files.

The reporters ``prometheus`` and ``junit`` write files for programs we do not control, so their tests parse the text
themselves, which proves nothing about the readers. This script feeds the files of a real diff (with hostile template
text, see ``make_samples.py``) to the readers, in Docker:

* ``promtool``      ``promtool check metrics`` of Prometheus on the ``.prom`` files;
* ``node-exporter`` the node exporter with the textfile collector scrapes the ``.prom`` file; the metrics must appear
                    and ``node_textfile_scrape_error`` must be 0;
* ``junit-xsd``     the JUnit file against the ``junit-10.xsd`` schema of the Jenkins xunit plugin (needs ``lxml``);
* ``jenkins``       a Jenkins controller with the JUnit plugin publishes the file; the failures it counts must be the
                    new alarming templates.

Usage: ``python bench/validate/reporters.py [all|promtool|node-exporter|junit-xsd|jenkins]``

Containers are named ``logfold-validate-*`` and removed at the end. Needs ``docker`` and the extension built
(``maturin develop --release``); ``junit-xsd`` runs with ``uv run --with lxml python bench/validate/reporters.py junit-xsd``.
"""

from __future__ import annotations

import hashlib
import http.cookiejar
import json
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE.parent / "data" / "validate"
PROMETHEUS_IMAGE = "prom/prometheus:v3.15.0"
NODE_EXPORTER_IMAGE = "prom/node-exporter:v1.12.1"
JENKINS_IMAGE = "jenkins/jenkins:2.580.1-lts-jdk21"
JUNIT_PLUGIN = "junit:1434.vde2d24df0c4c"
XSD_URL = (
    "https://raw.githubusercontent.com/jenkinsci/xunit-plugin/0afa700702a6617f483cfd9407711976dc0bd74a/"
    "src/main/resources/org/jenkinsci/plugins/xunit/types/model/xsd/junit-10.xsd"
)
XSD_SHA256 = "a1a816f58d1bf95ebabf371994df0b9246dee66ea9572fbec4f9296f1b2c0ff6"

JOB_CONFIG = """<?xml version='1.1' encoding='UTF-8'?>
<project>
  <builders>
    <hudson.tasks.Shell><command>cp /samples/{name} .</command></hudson.tasks.Shell>
  </builders>
  <publishers>
    <hudson.tasks.junit.JUnitResultArchiver>
      <testResults>{name}</testResults>
      <healthScaleFactor>1.0</healthScaleFactor>
    </hudson.tasks.junit.JUnitResultArchiver>
  </publishers>
</project>
"""


class Check:
    """The outcome of one check: a name, whether it passed, and a line of detail."""

    def __init__(self, name: str, ok: bool, detail: str) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail


def run(args: list[str], *, input_text: str | None = None, timeout: float = 600) -> subprocess.CompletedProcess[str]:
    """Run a command and capture its text output."""
    return subprocess.run(
        args, input=input_text, capture_output=True, text=True, encoding="utf-8", timeout=timeout, check=False
    )


def logfold(*args: str) -> None:
    """Run ``logfold`` through the current interpreter."""
    done = run([sys.executable, "-m", "logfold", *args])
    if done.returncode not in (0, 2):
        raise SystemExit(f"logfold {' '.join(args)} failed: {done.stderr}")


def make_files(work: Path) -> dict[str, Path]:
    """Write the sample logs and the reports of their diff; return the report files by name."""
    sys.path.insert(0, str(HERE))
    from make_samples import make_samples

    before, after = make_samples(work)
    files = {
        "diff.prom": work / "diff.prom",
        "analysis.prom": work / "analysis.prom",
        "logfold.xml": work / "logfold.xml",
    }
    logfold("diff", str(before), str(after), "--out", str(files["diff.prom"]), "-q")
    logfold("analyze", str(after), "--out", str(files["analysis.prom"]), "-q")
    logfold("diff", str(before), str(after), "--out", str(files["logfold.xml"]), "-q")
    logfold("diff", str(before), str(before), "--out", str(work / "clean.xml"), "-q")
    files["clean.xml"] = work / "clean.xml"
    return files


def remove(name: str) -> None:
    """Remove a container, ignoring a missing one."""
    run(["docker", "rm", "-f", name])


def check_promtool(work: Path, files: dict[str, Path]) -> list[Check]:
    """Lint the Prometheus files with ``promtool check metrics``."""
    checks = []
    for name in ("diff.prom", "analysis.prom"):
        done = run(
            [
                "docker", "run", "--rm", "-v", f"{work}:/w:ro", "--entrypoint", "sh", PROMETHEUS_IMAGE,
                "-c", f"promtool check metrics < /w/{files[name].name}",
            ]
        )  # fmt: skip
        checks.append(
            Check(
                f"promtool {name}",
                done.returncode == 0,
                "clean" if done.returncode == 0 else (done.stdout + done.stderr).strip(),
            )
        )
    return checks


def free_port() -> int:
    """Ask the system for a free local port (some ranges are reserved on Windows, so a fixed one may be refused)."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


OPENER = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))


def get(url: str, timeout: float = 5) -> bytes:
    """GET a URL and return the body; cookies are kept, Jenkins ties its CSRF crumb to the session."""
    with OPENER.open(url, timeout=timeout) as response:
        body: bytes = response.read()
    return body


def wait_for(url: str, seconds: float) -> bytes:
    """Poll a URL until it answers 200 or the time is over."""
    deadline = time.monotonic() + seconds
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return get(url)
        except (urllib.error.URLError, OSError) as error:
            last = error
            time.sleep(2)
    raise TimeoutError(f"{url} did not answer: {last}")


def check_node_exporter(work: Path, files: dict[str, Path]) -> list[Check]:
    """Scrape the diff file with the textfile collector of the node exporter."""
    textfile = work / "textfile"
    textfile.mkdir(exist_ok=True)
    (textfile / "logfold.prom").write_bytes(files["diff.prom"].read_bytes())
    name = "logfold-validate-node-exporter"
    port = free_port()
    remove(name)
    try:
        started = run(
            [
                "docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:9100",
                "-v", f"{textfile}:/tf:ro", NODE_EXPORTER_IMAGE,
                "--collector.disable-defaults", "--collector.textfile", "--collector.textfile.directory=/tf",
            ]
        )  # fmt: skip
        if started.returncode != 0:
            return [Check("node_exporter textfile", False, started.stderr.strip())]
        body = wait_for(f"http://127.0.0.1:{port}/metrics", 40).decode("utf-8")
    except TimeoutError as error:
        return [Check("node_exporter textfile", False, str(error))]
    finally:
        remove(name)
    error_line = next((line for line in body.splitlines() if line.startswith("node_textfile_scrape_error ")), "")
    series = [line for line in body.splitlines() if line.startswith("logfold_")]
    ok = error_line.endswith(" 0") and bool(series)
    return [
        Check("node_exporter textfile", ok, f"{error_line or 'no scrape_error line'}; {len(series)} logfold_ series")
    ]


def check_junit_xsd(files: dict[str, Path]) -> list[Check]:
    """Validate the JUnit files against the xunit plugin schema (pinned by commit and SHA-256)."""
    try:
        from lxml import etree  # type: ignore[import-untyped]
    except ImportError:
        return [
            Check("junit-10.xsd", False, "needs lxml: uv run --with lxml python bench/validate/reporters.py junit-xsd")
        ]
    DATA.mkdir(parents=True, exist_ok=True)
    schema_file = DATA / "junit-10.xsd"
    if not schema_file.exists():
        schema_file.write_bytes(get(XSD_URL, 30))
    if hashlib.sha256(schema_file.read_bytes()).hexdigest() != XSD_SHA256:
        return [Check("junit-10.xsd", False, f"{schema_file} does not match the pinned SHA-256")]
    schema = etree.XMLSchema(etree.parse(str(schema_file)))
    checks = []
    for name in ("logfold.xml", "clean.xml"):
        ok = schema.validate(etree.parse(str(files[name])))
        detail = "valid" if ok else "; ".join(f"line {e.line}: {e.message}" for e in list(schema.error_log)[:3])
        checks.append(Check(f"junit-10.xsd {name}", ok, detail))
    return checks


def post(base: str, path: str, data: bytes = b"", content_type: str = "application/xml") -> bytes:
    """POST to Jenkins with the CSRF crumb of the current session."""
    headers = {"Content-Type": content_type}
    try:
        crumb = json.loads(get(f"{base}/crumbIssuer/api/json"))
        headers[crumb["crumbRequestField"]] = crumb["crumb"]
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    request = urllib.request.Request(f"{base}{path}", data=data, method="POST", headers=headers)
    with OPENER.open(request, timeout=30) as response:
        body: bytes = response.read()
    return body


def jenkins_build(base: str, job: str, name: str) -> dict[str, object]:
    """Create a job that publishes ``name`` with the JUnit plugin, build it and return the test report."""
    post(base, f"/createItem?name={job}", JOB_CONFIG.format(name=name).encode("utf-8"))
    post(base, f"/job/{job}/build")
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        try:
            info = json.loads(get(f"{base}/job/{job}/lastBuild/api/json"))
        except urllib.error.HTTPError:
            time.sleep(2)
            continue
        if not info["building"]:
            tree = "failCount,passCount,skipCount,suites[cases[className,name,status]]"
            try:
                report = json.loads(get(f"{base}/job/{job}/lastBuild/testReport/api/json?tree={tree}"))
            except urllib.error.HTTPError:
                report = {}
            return {"result": info["result"], "report": report}
        time.sleep(2)
    raise TimeoutError(f"the build of {job} did not finish")


def check_jenkins(work: Path, files: dict[str, Path]) -> list[Check]:
    """Publish the JUnit files with the JUnit plugin of a throwaway Jenkins controller."""
    samples = work / "jenkins-samples"
    samples.mkdir(exist_ok=True)
    for name in ("logfold.xml", "clean.xml"):
        (samples / name).write_bytes(files[name].read_bytes())
    name = "logfold-validate-jenkins"
    port = free_port()
    remove(name)
    base = f"http://127.0.0.1:{port}"
    try:
        started = run(
            [
                "docker", "run", "-d", "--name", name, "-p", f"127.0.0.1:{port}:8080",
                "-v", f"{samples}:/samples:ro", "-e", "JAVA_OPTS=-Djenkins.install.runSetupWizard=false",
                "--entrypoint", "bash", JENKINS_IMAGE, "-c",
                f"jenkins-plugin-cli --plugins {JUNIT_PLUGIN} && exec /usr/bin/tini -- /usr/local/bin/jenkins.sh",
            ]
        )  # fmt: skip
        if started.returncode != 0:
            return [Check("jenkins junit", False, started.stderr.strip())]
        wait_for(f"{base}/login", 420)
        expected_failures = int(files["logfold.xml"].read_text(encoding="utf-8").split('failures="')[1].split('"')[0])
        found = jenkins_build(base, "diff", "logfold.xml")
        report = found["report"]
        assert isinstance(report, dict)
        cases = [case for suite in report.get("suites", []) for case in suite["cases"]]
        failed = report.get("failCount")
        ok = failed == expected_failures and found["result"] == "UNSTABLE"
        checks = [
            Check(
                "jenkins junit logfold.xml",
                ok,
                f"build {found['result']}, {failed} failed of {len(cases)} cases (expected {expected_failures})",
            )
        ]
        clean = jenkins_build(base, "clean", "clean.xml")
        clean_report = clean["report"]
        assert isinstance(clean_report, dict)
        passed = clean_report.get("passCount")
        checks.append(
            Check(
                "jenkins junit clean.xml",
                passed == 1 and clean["result"] == "SUCCESS",
                f"build {clean['result']}, {passed} passed",
            )
        )
        return checks
    except (TimeoutError, urllib.error.URLError, OSError, KeyError, ValueError) as error:
        logs = run(["docker", "logs", "--tail", "15", name]).stdout
        return [Check("jenkins junit", False, f"{error}\n{logs}")]
    finally:
        remove(name)


def main(argv: list[str]) -> int:
    """Run the requested checks and print one line for each."""
    which = argv[1] if len(argv) > 1 else "all"
    steps: dict[str, Callable[[Path, dict[str, Path]], list[Check]]] = {
        "promtool": check_promtool,
        "node-exporter": check_node_exporter,
        "junit-xsd": lambda _work, files: check_junit_xsd(files),
        "jenkins": check_jenkins,
    }
    if which != "all" and which not in steps:
        raise SystemExit(__doc__)
    chosen = list(steps) if which == "all" else [which]
    checks: list[Check] = []
    with tempfile.TemporaryDirectory(prefix="logfold-validate-") as directory:
        work = Path(directory)
        files = make_files(work)
        for step in chosen:
            checks.extend(steps[step](work, files))
    for check in checks:
        print(f"{'ok  ' if check.ok else 'FAIL'}  {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
