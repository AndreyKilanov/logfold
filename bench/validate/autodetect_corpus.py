"""The files and the damaged heads of the detection matrix (used by ``autodetect.py``).

Every file has a **truth**: the format that is meant for it (``None`` when no built-in format reads it). Files come from
four places: logs that real programs wrote (``formats.py`` with ``LOGFOLD_KEEP_LOGS``), logs of other projects
(``external_samples.py``), the 16 Loghub-2k sets and the four Loghub-2.0 logs, and the datasets that ``bench/data.py``
makes. A long file is cut to its first ``LINES`` lines. Each file is then read in several damaged forms (``VARIANTS``).
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bench"))

from data import fetch_loghub  # noqa: E402
from external_samples import CACHE, fetch  # noqa: E402
from keep_logs import SEPARATOR  # noqa: E402

DATA = ROOT / "bench" / "data"
KEPT = CACHE.parent / "real"
LINES = 20_000
LOGHUB_2K = {
    "Android": None,
    "Apache": None,
    "BGL": None,
    "HDFS": None,
    "HPC": None,
    "Hadoop": "app",
    "HealthApp": None,
    "Linux": "syslog",
    "Mac": "syslog",
    "OpenSSH": "syslog",
    "OpenStack": None,
    "Proxifier": None,
    "Spark": None,
    "Thunderbird": None,
    "Windows": None,
    "Zookeeper": None,
}
LOGHUB_2 = {"bgl": None, "hdfs": None, "spark": None, "thunderbird": None}
GENERATED = {"app_10mb.log": "app", "nginx_100mb.log": "nginx", "highcard_10mb.log": None, "loghub_100mb.log": None}
BANNER = [
    b"=== MyService 4.2.1 starting ===",
    b"java.version=21.0.4 os=Linux 6.8 cpus=8",
    b"Loading configuration from /etc/myservice/main.conf",
    b"Listening on port 8080",
    b"",
]
PROSE = "Loading configuration item {n} from the defaults of the service"


@dataclass(frozen=True)
class Entry:
    """One log file and the format that is meant for it (``None``: no built-in format reads it)."""

    source: str
    name: str
    path: Path
    truth: str | None


def head(path: Path, lines: int, target: Path) -> Path:
    """Write the first ``lines`` lines of ``path`` to ``target`` (as bytes) and return ``target``."""
    with path.open("rb") as stream, target.open("wb") as out:
        for _, raw in zip(range(lines), stream, strict=False):
            out.write(raw)
    return target


def real_logs() -> list[Entry]:
    """Return the logs that the real programs wrote and that ``formats.py`` kept, with the format each was read with."""
    found = []
    for log in sorted(KEPT.glob("*.log")):
        spec = log.with_suffix(".format").read_text(encoding="utf-8")
        found.append(Entry("real programs", log.stem.split(SEPARATOR, 1)[1], log, spec))
    return found


def external_logs() -> list[Entry]:
    """Return the logs of other projects, and the logs of the workflow runs when they are in the cache."""
    found = [
        Entry("other projects", sample.name, sample.log, true_format(sample.log, sample.format)) for sample in fetch()
    ]
    for log in sorted((CACHE / "gha").glob("*/*.txt")):
        found.append(Entry("other projects", f"gha:{log.parent.name}/{log.name}", log, "github-actions"))
    return found


def true_format(log: Path, spec: str) -> str:
    """Return the format that is really meant for a sample.

    The test inputs of Fluent Bit's Docker mode keep only the ``log`` key of Docker's line (no ``stream``, no ``time``): they
    are inputs of a parser, not files that Docker wrote, and what they hold is plain JSON lines with a message.
    """
    if spec == "docker-json" and b'"stream"' not in log.read_bytes()[:2000]:
        return "jsonl"
    return spec


def loghub_logs(scratch: Path) -> list[Entry]:
    """Return the 16 Loghub-2k sets and the first lines of the four Loghub-2.0 logs."""
    found = []
    for name, truth in LOGHUB_2K.items():
        found.append(Entry("Loghub-2k", name, fetch_loghub_file(name), truth))
    for name, truth in LOGHUB_2.items():
        source = DATA / "loghub2" / f"{name}.txt"
        if source.exists():
            found.append(Entry("Loghub-2.0", name, head(source, LINES, scratch / f"{name}.txt"), truth))
    return found


def fetch_loghub_file(name: str) -> Path:
    """Download a Loghub-2k set once and return its path."""
    cache = DATA / "seeds"
    fetch_loghub(name, cache)
    return cache / f"{name}_2k.log"


def generated_logs(scratch: Path) -> list[Entry]:
    """Return the first lines of the datasets that ``bench/data.py`` makes, when they exist."""
    found = []
    for name, truth in GENERATED.items():
        source = DATA / name
        if source.exists():
            found.append(Entry("generated", name, head(source, LINES, scratch / name), truth))
    return found


def with_banner(data: bytes) -> bytes:
    """Put the start-up banner of a program in front of the log."""
    return b"\n".join(BANNER) + b"\n" + data


def with_prose(count: int) -> Callable[[bytes], bytes]:
    """Return a damage that puts ``count`` lines of plain text in front of the log."""
    text = "\n".join(PROSE.format(n=n) for n in range(count)).encode() + b"\n"
    return lambda data: text + data


def crlf(data: bytes) -> bytes:
    """Give every line the Windows line ending."""
    return data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")


VARIANTS: dict[str, Callable[[bytes], bytes]] = {
    "clean": lambda data: data,
    "bom": lambda data: b"\xef\xbb\xbf" + data,
    "crlf": crlf,
    "blank-head": lambda data: b"\n" * 50 + data,
    "banner": with_banner,
    "cut-first": lambda data: data[12:],
    "prose-100": with_prose(100),
    "prose-200": with_prose(200),
}
