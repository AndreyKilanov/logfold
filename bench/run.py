"""Benchmark runner: logfold against Drain3, logdrain and logdelta.

Every command runs as a separate process; the runner records wall time, CPU time (user + system) and peak working set
with ``psutil``. Results go to ``bench/results/<date>/results.json``; ``bench/report.py`` renders the Markdown tables.
The protocol is described in ``bench/PROTOCOL.md``.

Usage::

    python bench/run.py --repeat 3
    python bench/run.py --scenario diff --datasets nginx app
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
CORES = os.cpu_count() or 1


@dataclass
class Sample:
    wall_s: float
    cpu_s: float
    peak_mb: float
    returncode: int


def measure(command: list[str], timeout: float) -> Sample:
    """Run ``command`` and sample its resource use until it exits."""
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handle = psutil.Process(process.pid)
    peak = 0.0
    cpu = 0.0
    while process.poll() is None:
        if time.perf_counter() - started > timeout:
            for child in handle.children(recursive=True):
                child.kill()
            process.kill()
            process.wait()
            return Sample(timeout, cpu, peak, -9)
        try:
            tree = [handle, *handle.children(recursive=True)]
            rss = 0.0
            cpu_now = 0.0
            for member in tree:
                try:
                    info = member.memory_info()
                    rss += getattr(info, "peak_wset", info.rss)
                    times = member.cpu_times()
                    cpu_now += times.user + times.system
                except psutil.Error:
                    continue
            peak = max(peak, rss / 1e6)
            cpu = max(cpu, cpu_now)
        except psutil.Error:
            break
        time.sleep(0.02)
    process.wait()
    code = process.returncode
    if code == 1 and "diff" in command and Path(command[0]).stem == "logdelta":
        code = 0
    return Sample(time.perf_counter() - started, cpu, peak, code)


def logfold(*args: str) -> list[str]:
    return [PYTHON, "-m", "logfold", *args]


def analyze_commands(path: Path, masked: bool) -> dict[str, list[str]]:
    common = ["-f", "plain", "--top", "1", "-q", "--engine", "native"]
    mask_flag: list[str] = [] if masked else ["--no-masks"]
    commands = {
        "logfold 1 thread": logfold("analyze", str(path), *common, *mask_flag, "--strategy", "sequential"),
        f"logfold {CORES} threads": logfold(
            "analyze",
            str(path),
            *common,
            *mask_flag,
            "--strategy",
            "chunked",
            "--threads",
            str(CORES),
            "--chunk-mb",
            "8",
        ),
        "Drain3 (Python)": [
            PYTHON,
            str(ROOT / "bench" / "competitors" / "drain3_run.py"),
            str(path),
            "--masks",
            "default" if masked else "none",
        ],
    }
    logdrain = shutil.which("logdrain")
    if logdrain:
        flags = ["--format", "csv", "--min-size", "999999999", "--sim-th", "0.4", "--depth", "4"]
        if masked:
            flags += ["--masks", "uuid,hex32,ipv4"]
        commands["logdrain (Rust)"] = [logdrain, str(path), *flags]
    logdelta = shutil.which("logdelta")
    if logdelta and masked:
        commands["logdelta (Rust)"] = [logdelta, "templates", str(path), "--threshold", "0.4", "--json", "-n", "1"]
    return commands


def diff_commands(before: Path, after: Path) -> dict[str, list[str]]:
    common = ["-f", "plain", "--json", "-q", "--engine", "native"]
    commands = {
        "logfold diff 1 thread": logfold("diff", str(before), str(after), *common, "--strategy", "sequential"),
        f"logfold diff {CORES} threads": logfold(
            "diff",
            str(before),
            str(after),
            *common,
            "--strategy",
            "chunked",
            "--threads",
            str(CORES),
            "--chunk-mb",
            "8",
        ),
        f"logfold diff {CORES} threads, --no-recount": logfold(
            "diff",
            str(before),
            str(after),
            *common,
            "--strategy",
            "chunked",
            "--threads",
            str(CORES),
            "--chunk-mb",
            "8",
            "--no-recount",
        ),
    }
    logdelta = shutil.which("logdelta")
    if logdelta:
        commands["logdelta diff (Rust)"] = [
            logdelta,
            "diff",
            str(before),
            "--target",
            str(after),
            "--threshold",
            "0.4",
            "--json",
        ]
    return commands


def tool_versions() -> dict[str, str]:
    def first_line(command: list[str]) -> str:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=False)
        except OSError:
            return "unavailable"
        return (result.stdout or result.stderr).strip().splitlines()[0] if (result.stdout or result.stderr) else "?"

    versions = {"logfold": first_line(logfold("--version"))}
    for name in ("logdrain", "logdelta"):
        path = shutil.which(name)
        versions[name] = first_line([path, "--version"]) if path else "not installed"
    versions["drain3"] = first_line(
        [PYTHON, "-c", "import importlib.metadata as m; print('drain3', m.version('drain3'))"]
    )
    return versions


def environment() -> dict[str, object]:
    return {
        "date": date.today().isoformat(),
        "os": platform.platform(),
        "cpu": platform.processor(),
        "cores_logical": CORES,
        "cores_physical": psutil.cpu_count(logical=False),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "python": platform.python_version(),
        "tools": tool_versions(),
    }


def summarize(samples: list[Sample]) -> dict[str, object]:
    ok = [s for s in samples if s.returncode == 0]
    if not ok:
        return {"failed": True, "runs": [asdict(s) for s in samples]}
    walls = [s.wall_s for s in ok]
    return {
        "wall_median_s": statistics.median(walls),
        "wall_min_s": min(walls),
        "wall_max_s": max(walls),
        "cpu_median_s": statistics.median(s.cpu_s for s in ok),
        "peak_mb_max": max(s.peak_mb for s in ok),
        "runs": [asdict(s) for s in samples],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "bench" / "data")
    parser.add_argument("--size-mb", type=int, default=100)
    parser.add_argument("--datasets", nargs="*", default=["nginx", "app", "loghub", "highcard"])
    parser.add_argument("--scenario", nargs="*", default=["analyze-bare", "analyze-masked", "diff"])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    out = args.out or ROOT / "bench" / "results" / date.today().isoformat() / "results.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {
        "environment": environment(),
        "args": vars(args) | {"data": str(args.data)},
        "runs": [],
    }
    for scenario in args.scenario:
        for name in args.datasets:
            path = args.data / f"{name}_{args.size_mb}mb.log"
            if scenario == "diff":
                after = args.data / f"{name}_{args.size_mb}mb_b.log"
                if not after.exists():
                    continue
                commands = diff_commands(path, after)
                size = path.stat().st_size + after.stat().st_size
            else:
                commands = analyze_commands(path, masked=scenario == "analyze-masked")
                size = path.stat().st_size
            for tool, command in commands.items():
                samples = []
                for attempt in range(args.repeat):
                    sample = measure(command, args.timeout)
                    samples.append(sample)
                    if sample.returncode != 0:
                        break
                    print(
                        f"{scenario:15} {name:9} {tool:36} #{attempt + 1}: {sample.wall_s:7.2f}s rc={sample.returncode}",
                        flush=True,
                    )
                results["runs"].append(  # type: ignore[union-attr]
                    {
                        "scenario": scenario,
                        "dataset": name if args.size_mb == 100 else f"{name}@{args.size_mb}MB",
                        "tool": tool,
                        "input_bytes": size,
                        "command": [Path(c).name if os.sep in c and not c.startswith("-") else c for c in command],
                        **summarize(samples),
                    }
                )
                out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
