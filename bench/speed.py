"""Speed and memory of logfold, and of the other tools on the same work: one script, the flags choose what is measured.

Every command runs as a separate process; the script records wall time, CPU time and the peak working set of the process
tree (``psutil``), repeats it ``--repeat`` times and prints one Markdown table with the medians. The raw numbers of the run are also saved to ``bench/results/`` (a folder that is
git-ignored and created on demand); ``--out FILE`` chooses another file and ``--no-save`` skips it.

``analyze`` folds each file into templates with every chosen variant of logfold and, if installed, the competitors::

    python bench/speed.py analyze bench/data/nginx_100mb.log --repeat 3
    python bench/speed.py analyze FILE --strategy auto chunked sequential --no-masks
    python bench/speed.py analyze FILE --strategy chunked --warm-start --chunk-mb 64
    python bench/speed.py analyze FILE --tools drain3 logdrain logdelta

``diff`` compares two logs (the "after" run of a generated pair is ``NAME_100mb_b.log``)::

    python bench/speed.py diff bench/data/app_100mb.log bench/data/app_100mb_b.log

``formats`` times the built-in log formats against ``-f plain`` (every line is a message, nothing is parsed) on generated logs::

    python bench/speed.py formats --sizes 10 100
    python bench/speed.py formats --format haproxy log4j

``matchers`` times each native matcher alone on lists of one-sided templates (the cost a plugin matcher adds to a diff)::

    python bench/speed.py matchers --sizes 5000 20000 100000

Inputs come from ``bench/data.py``. The speed of the pure-Python reference engine is not measured.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import random
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import psutil
from data import GENERATORS

ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CORES = os.cpu_count() or 1
TOOLS = ("drain3", "logdrain", "logdelta")
SHAPES = {"sparse": 3000, "dense": 300}
MATCHERS = {
    "jaccard": ("jaccard", 0.6),
    "jaccard-idf": ("jaccard_idf", 0.5),
    "overlap": ("overlap", 0.8),
    "rules": ("rules", None),
}


@dataclass
class Sample:
    """One run of one command."""

    wall_s: float
    cpu_s: float
    peak_mb: float
    returncode: int


def measure(command: list[str], timeout: float) -> Sample:
    """Run ``command`` and sample the resource use of its process tree until it exits."""
    started = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    handle = psutil.Process(process.pid)
    peak = cpu = 0.0
    while process.poll() is None:
        if time.perf_counter() - started > timeout:
            for child in handle.children(recursive=True):
                child.kill()
            process.kill()
            process.wait()
            return Sample(timeout, cpu, peak, -9)
        rss = cpu_now = 0.0
        try:
            for member in [handle, *handle.children(recursive=True)]:
                try:
                    info = member.memory_info()
                    rss += getattr(info, "peak_wset", info.rss)
                    times = member.cpu_times()
                    cpu_now += times.user + times.system
                except psutil.Error:
                    continue
        except psutil.Error:
            break
        peak, cpu = max(peak, rss / 1e6), max(cpu, cpu_now)
        time.sleep(0.02)
    process.wait()
    return Sample(time.perf_counter() - started, cpu, peak, process.returncode)


def logfold(*args: str) -> list[str]:
    """The command line of ``python -m logfold``."""
    return [PYTHON, "-m", "logfold", *args]


def analyze_variants(path: Path, args: argparse.Namespace) -> dict[str, list[str]]:
    """The commands that fold ``path`` into templates: logfold variants first, then the chosen competitors."""
    common = ["-f", args.format, "--top", "1", "-q", "--engine", "native"]
    masks = [] if args.masks else ["--no-masks"]
    variants: dict[str, list[str]] = {}
    for strategy in args.strategy:
        threads = [] if strategy == "sequential" else ["--threads", str(args.threads), "--chunk-mb", str(args.chunk_mb)]
        label = f"logfold {strategy}" + ("" if strategy == "sequential" else f", {args.threads} threads")
        variants[label] = logfold("analyze", str(path), *common, *masks, "--strategy", strategy, *threads)
        if args.warm_start and strategy != "sequential":
            variants[label + ", warm start"] = variants[label] + ["--warm-start"]
    if args.high_cardinality:
        variants["logfold high-cardinality"] = logfold("analyze", str(path), *common, *masks, "--high-cardinality")
    if "drain3" in args.tools:
        variants["Drain3 (Python)"] = [
            PYTHON,
            str(Path(__file__)),
            "drain3",
            str(path),
            "--masks",
            "default" if args.masks else "none",
        ]
    if (logdrain := shutil.which("logdrain")) and "logdrain" in args.tools:
        flags = ["--format", "csv", "--min-size", "999999999", "--sim-th", "0.4", "--depth", "4"]
        variants["logdrain (Rust)"] = [
            logdrain,
            str(path),
            *flags,
            *(["--masks", "uuid,hex32,ipv4"] if args.masks else []),
        ]
    if (logdelta := shutil.which("logdelta")) and "logdelta" in args.tools and args.masks:
        variants["logdelta (Rust)"] = [logdelta, "templates", str(path), "--threshold", "0.4", "--json", "-n", "1"]
    return variants


def diff_variants(before: Path, after: Path, args: argparse.Namespace) -> dict[str, list[str]]:
    """The commands that compare two logs."""
    common = ["-f", args.format, "--json", "-q", "--engine", "native"]
    chunked = ["--strategy", "chunked", "--threads", str(args.threads), "--chunk-mb", str(args.chunk_mb)]
    variants = {
        "logfold diff, 1 thread": logfold("diff", str(before), str(after), *common, "--strategy", "sequential"),
        f"logfold diff, {args.threads} threads": logfold("diff", str(before), str(after), *common, *chunked),
        f"logfold diff, {args.threads} threads, --no-recount": logfold(
            "diff", str(before), str(after), *common, *chunked, "--no-recount"
        ),
    }
    if (logdelta := shutil.which("logdelta")) and "logdelta" in args.tools:
        variants["logdelta diff (Rust)"] = [
            logdelta,
            "diff",
            str(before),
            "--target",
            str(after),
            "--threshold",
            "0.4",
            "--json",
        ]
    return variants


def run_variants(variants: dict[str, list[str]], source: str, size: int, args: argparse.Namespace) -> None:
    """Measure every command ``--repeat`` times and print its row."""
    for label, command in variants.items():
        samples = []
        for _ in range(args.repeat):
            samples.append(measure(command, args.timeout))
            if samples[-1].returncode not in (0, 1) or (
                samples[-1].returncode == 1 and not label.startswith("logdelta diff")
            ):
                break
        ok = (0, 1) if label.startswith("logdelta diff") else (0,)  # logdelta exits with 1 when the logs differ
        good = [s for s in samples if s.returncode in ok]
        row: dict[str, object] = {
            "input": source,
            "variant": label,
            "size_bytes": size,
            "runs": [asdict(s) for s in samples],
        }
        args.rows.append(row)
        if not good:
            print(f"| {label} | failed (exit code {samples[-1].returncode}) | | | |", flush=True)
            continue
        wall = statistics.median(s.wall_s for s in good)
        row |= {
            "wall_median_s": wall,
            "cpu_median_s": statistics.median(s.cpu_s for s in good),
            "peak_mb_max": max(s.peak_mb for s in good),
        }
        print(
            f"| {label} | {wall:.2f} s | {size / 1e6 / wall:,.0f} MB/s | {statistics.median(s.cpu_s for s in good):.1f} s | "
            f"{max(s.peak_mb for s in good):,.0f} MB |",
            flush=True,
        )


def header(title: str) -> None:
    print(
        f"\n### {title}\n\n| variant | wall (median) | throughput | CPU | peak memory |\n|---|---:|---:|---:|---:|",
        flush=True,
    )


def analyze(args: argparse.Namespace) -> None:
    """``analyze``: each file with each variant."""
    files = args.files or sorted((ROOT / "bench" / "data").glob("*_100mb.log"))
    if not files:
        sys.exit("no input: pass files, or generate some with `python bench/data.py make`")
    for path in files:
        header(f"{path.name} ({path.stat().st_size / 1e6:,.0f} MB, {'masks' if args.masks else 'no masks'})")
        run_variants(analyze_variants(path, args), path.name, path.stat().st_size, args)


def diff(args: argparse.Namespace) -> None:
    """``diff``: two logs with each variant."""
    before, after = args.before, args.after
    header(f"diff {before.name} {after.name}")
    run_variants(
        diff_variants(before, after, args),
        f"{before.name} {after.name}",
        before.stat().st_size + after.stat().st_size,
        args,
    )


def templates(rng: random.Random, count: int, vocabulary: int) -> list[str]:
    """Templates like the one-sided templates of a diff: a level, a service, a few words."""
    words = [f"w{i}" for i in range(vocabulary)]
    return [
        " ".join(["INFO", f"svc{rng.randrange(count // 4)}", *(rng.choice(words) for _ in range(rng.randrange(3, 9)))])
        for _ in range(count)
    ]


def matchers(args: argparse.Namespace) -> None:
    """``matchers``: each native matcher alone on lists of one-sided templates."""
    from logfold import _bridge as native

    if not native.supports_matching():
        sys.exit("the native extension is not built: run `maturin develop --release`")
    print(
        "\n| shape | templates per side | " + " | ".join(args.matcher) + " |\n|---|---:|" + "---:|" * len(args.matcher)
    )
    series: dict[tuple[str, str], list[float]] = {}
    for shape in args.shape:
        for size in args.sizes:
            rng = random.Random(size)
            before, after = templates(rng, size, SHAPES[shape]), templates(rng, size, SHAPES[shape])
            rules = [(before[i], after[i]) for i in range(0, size, max(size // 2000, 1))]
            cells = []
            for name in args.matcher:
                kind, threshold = MATCHERS[name]
                best = math.inf
                for _ in range(args.repeat):
                    started = time.perf_counter()
                    native.match_templates(kind, before, after, threshold, rules if kind == "rules" else None)
                    best = min(best, time.perf_counter() - started)
                series.setdefault((shape, name), []).append(best)
                args.rows.append({"shape": shape, "size": size, "matcher": name, "seconds": best})
                cells.append(f"{best:.3f} s")
            print(f"| {shape} | {size:,} | " + " | ".join(cells) + " |", flush=True)
    if len(args.sizes) > 1:
        ratio = math.log(args.sizes[-1] / args.sizes[0])
        print("\ngrowth t ~ n^k between the smallest and the largest size:")
        for (shape, name), times in series.items():
            print(f"- {shape} {name}: k = {math.log(times[-1] / times[0]) / ratio:.2f}")


def formats(args: argparse.Namespace) -> None:
    """``formats``: each format against ``plain`` on a generated log; also checks that every line parses."""
    from data import GENERATORS, write_format_log

    import logfold as library

    print(
        "\n| format | size | MB/s with the format | MB/s plain | format / plain | peak memory | unparsed lines |\n|---|---:|---:|---:|---:|---:|---:|"
    )
    with tempfile.TemporaryDirectory(dir=ROOT / "bench") as folder:
        for name in args.format:
            for size in args.sizes:
                path = Path(folder) / f"{name}_{size}mb.log"
                write_format_log(name, size, path)
                speed: dict[str, float] = {}
                peak = 0.0
                for fmt in (name, "plain"):
                    command = logfold("analyze", str(path), "-f", fmt, "--top", "1", "-q", "--engine", "native")
                    runs = [measure(command, args.timeout) for _ in range(args.repeat)]
                    speed[fmt] = size / statistics.median(run.wall_s for run in runs)
                    peak = max(peak, *(run.peak_mb for run in runs)) if fmt == name else peak
                unparsed = ""
                if size == min(args.sizes):
                    unparsed = str(library.analyze(path, format=name, engine="native", examples="none").run.unparsed)
                path.unlink()
                row = {
                    "format": name,
                    "size_mb": size,
                    "mb_per_s": speed[name],
                    "plain_mb_per_s": speed["plain"],
                    "peak_mb": peak,
                    "unparsed": unparsed,
                }
                args.rows.append(row)
                print(
                    f"| {name} | {size} MB | {speed[name]:,.0f} | {speed['plain']:,.0f} | {speed[name] / speed['plain']:.2f} | {peak:,.0f} MB | {unparsed} |",
                    flush=True,
                )
    assert set(args.format) <= set(GENERATORS)


def drain3(args: argparse.Namespace) -> None:
    """Hidden mode used by ``analyze``: run Drain3 over a file with parameters aligned with the logfold defaults."""
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig

    from logfold.config import DEFAULT_MASKS

    config = TemplateMinerConfig()
    config.drain_depth, config.drain_sim_th, config.drain_max_children = 4, 0.4, 100
    config.profiling_enabled = False
    if args.masks == "default":
        config.masking_instructions = [
            MaskingInstruction(rule.pattern, rule.token.strip("<>")) for rule in DEFAULT_MASKS
        ]
    miner = TemplateMiner(config=config)
    with open(args.path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            miner.add_log_message(line.rstrip("\n"))


def parser() -> argparse.ArgumentParser:
    """The command line."""
    main = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = main.add_subparsers(dest="what", required=True)

    def saving(command: argparse.ArgumentParser) -> None:
        command.add_argument(
            "--out", type=Path, help="write the raw numbers here (default: a new file in bench/results/)"
        )
        command.add_argument("--no-save", action="store_true", help="do not write the raw numbers")

    def common(command: argparse.ArgumentParser) -> None:
        saving(command)
        command.add_argument("--repeat", type=int, default=3, help="runs per variant; the median is shown (default 3)")
        command.add_argument("--timeout", type=float, default=1800, help="seconds before a run is stopped")
        command.add_argument("--format", default="plain", help="logfold --format (default plain)")
        command.add_argument("--threads", type=int, default=CORES, help="threads of the chunked strategy")
        command.add_argument("--chunk-mb", type=int, default=8, help="chunk size of the chunked strategy")
        command.add_argument(
            "--tools", nargs="*", default=[], choices=TOOLS, help="competitors to run too (if installed)"
        )

    first = sub.add_parser("analyze", help="fold files into templates")
    first.add_argument("files", nargs="*", type=Path, help="log files (default: bench/data/*_100mb.log)")
    first.add_argument(
        "--strategy", nargs="+", default=["sequential", "chunked"], choices=("sequential", "chunked", "auto")
    )
    first.add_argument("--no-masks", dest="masks", action="store_false", help="mine without the default masks")
    first.add_argument("--warm-start", action="store_true", help="also run the chunked strategy with --warm-start")
    first.add_argument("--high-cardinality", action="store_true", help="also run --high-cardinality")
    common(first)
    first.set_defaults(run=analyze)

    second = sub.add_parser("diff", help="compare two logs")
    second.add_argument("before", type=Path)
    second.add_argument("after", type=Path)
    common(second)
    second.set_defaults(run=diff)

    fourth = sub.add_parser("formats", help="each built-in format against plain")
    fourth.add_argument("--format", nargs="+", default=list(GENERATORS), choices=list(GENERATORS))
    fourth.add_argument("--sizes", nargs="+", type=int, default=[10, 100], help="log sizes in MB (default 10 100)")
    fourth.add_argument("--repeat", type=int, default=3, help="runs per cell; the median is shown")
    fourth.add_argument("--timeout", type=float, default=1800, help="seconds before a run is stopped")
    saving(fourth)
    fourth.set_defaults(run=formats)

    third = sub.add_parser("matchers", help="each native matcher alone on one-sided templates")
    third.add_argument("--sizes", nargs="+", type=int, default=[5000, 20000, 100000], help="templates per side")
    third.add_argument("--matcher", nargs="+", default=list(MATCHERS), choices=list(MATCHERS))
    third.add_argument(
        "--shape", nargs="+", default=list(SHAPES), choices=list(SHAPES), help="sparse: few shared words; dense: many"
    )
    third.add_argument("--repeat", type=int, default=3, help="runs per cell; the best is shown")
    saving(third)
    third.set_defaults(run=matchers)

    hidden = sub.add_parser("drain3")
    hidden.add_argument("path")
    hidden.add_argument("--masks", choices=("none", "default"), default="none")
    hidden.set_defaults(run=drain3, no_save=True)
    return main


def main() -> None:
    """Run the chosen measurement."""
    args = parser().parse_args()
    args.rows = []
    args.run(args)
    if args.what != "drain3" and not args.no_save and args.rows:
        save(args)


def save(args: argparse.Namespace) -> None:
    """Write the raw numbers of the run to ``--out`` (default: a new file in ``bench/results/``)."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = args.out or ROOT / "bench" / "results" / f"speed-{args.what}-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    settings = {
        key: str(value) if isinstance(value, Path) else value
        for key, value in vars(args).items()
        if key not in ("run", "rows")
    }
    settings["files"] = [str(path) for path in settings.get("files", [])]
    machine = {
        "os": platform.platform(),
        "cores_logical": CORES,
        "cores_physical": psutil.cpu_count(logical=False),
        "ram_gb": round(psutil.virtual_memory().total / 1e9, 1),
        "python": platform.python_version(),
    }
    payload = {
        "what": args.what,
        "date": datetime.now().isoformat(timespec="seconds"),
        "machine": machine,
        "args": settings,
        "rows": args.rows,
    }
    out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
