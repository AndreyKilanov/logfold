"""What ``logfold diff --new-values`` costs, and whether it keeps its promises on a log that is hard for it.

``pairs`` times ``diff`` against ``diff --new-values`` on the "before" and "after" logs of ``data.py make`` (time and peak
memory, medians)::

    python bench/data.py make --size-mb 100 --only nginx app
    python bench/data.py make --size-mb 100 --variant b --only nginx app
    python bench/new_values.py pairs

``stress`` writes two logs that every line of which has a request id that is new (as nginx ``$request_id``) and a user id
among 200,000 (40,000 of them new in the second log), then runs ``--new-values`` with each strategy: the position of the
user must be compared (not ``capped``) whatever the strategy, because a position that is new on every record must not
use up the room of the others::

    python bench/new_values.py stress --lines 1500000

The raw numbers go to ``bench/results/`` (git-ignored); ``--no-save`` skips them.
"""

from __future__ import annotations

import argparse
import json
import random
import statistics
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from speed import measure

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "bench" / "data"
PAIRS = {"nginx": "nginx", "app": "auto"}
TIMEOUT = 900.0


def command(before: Path, after: Path, fmt: str, *extra: str) -> list[str]:
    """The command line of one diff."""
    return [sys.executable, "-m", "logfold", "diff", str(before), str(after), "-f", fmt, "--json", "-q", *extra]


def pairs(args: argparse.Namespace) -> list[dict[str, object]]:
    """Time ``diff`` and ``diff --new-values`` on the generated pairs."""
    rows: list[dict[str, object]] = []
    print("| log | diff | diff --new-values | ratio | peak memory |\n|---|---:|---:|---:|---:|")
    for name, fmt in PAIRS.items():
        before, after = DATA / f"{name}_{args.size}mb.log", DATA / f"{name}_{args.size}mb_b.log"
        if not (before.exists() and after.exists()):
            print(f"| {name} | missing: python bench/data.py make --size-mb {args.size} (and --variant b) | | | |")
            continue
        plain = [measure(command(before, after, fmt), TIMEOUT) for _ in range(args.repeat)]
        asked = [measure(command(before, after, fmt, "--new-values"), TIMEOUT) for _ in range(args.repeat)]
        wall = statistics.median(s.wall_s for s in plain), statistics.median(s.wall_s for s in asked)
        peak = max(s.peak_mb for s in plain), max(s.peak_mb for s in asked)
        print(
            f"| {name} | {wall[0]:.2f} s | {wall[1]:.2f} s | {wall[1] / wall[0]:.1f}x | {peak[0]:.0f} -> {peak[1]:.0f} MB |"
        )
        rows.append({"log": name, "plain_s": wall[0], "new_values_s": wall[1], "peak_mb": peak})
    return rows


def write_stress(directory: Path, lines: int) -> tuple[Path, Path]:
    """Write the two logs of the stress test (the same seed gives the same bytes)."""
    rng = random.Random(11)
    paths = directory / "requests_a.log", directory / "requests_b.log"
    for path, users in zip(paths, (range(200_000), range(40_000, 240_000)), strict=True):
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            for _ in range(lines):
                handle.write(f"req {rng.getrandbits(128):032x} user u{rng.choice(users)} status 200\n")
    return paths


def stress(args: argparse.Namespace) -> list[dict[str, object]]:
    """Run ``--new-values`` on the stress logs with each strategy and check that the user position is compared."""
    rows: list[dict[str, object]] = []
    DATA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=DATA) as directory:
        before, after = write_stress(Path(directory), args.lines)
        report = Path(directory) / "report.json"
        print("| strategy | time | peak memory | positions (capped) | users new / before |\n|---|---:|---:|---|---|")
        for strategy in ("sequential", "chunked"):
            with report.open("w", encoding="utf-8") as handle:
                sample_command = command(before, after, "plain", "--new-values", "--strategy", strategy)
                process = subprocess.run(sample_command, stdout=handle, check=False, timeout=TIMEOUT)
            sample = measure(sample_command, TIMEOUT)
            if process.returncode:
                print(f"| {strategy} | failed with exit code {process.returncode} | | | |")
                continue
            positions = [
                position
                for item in json.loads(report.read_text(encoding="utf-8"))["value_changes"]
                for position in item["positions"]
            ]
            capped = [position["position"] for position in positions if position["capped"]]
            users = next((position for position in positions if position["position"] == 3), None)
            counts = f"{users['new_distinct']:,} / {users['before_distinct']:,}" if users else "-"
            print(f"| {strategy} | {sample.wall_s:.2f} s | {sample.peak_mb:.0f} MB | {capped} | {counts} |")
            rows.append({"strategy": strategy, "wall_s": sample.wall_s, "peak_mb": sample.peak_mb, "capped": capped})
            if 3 in capped:
                print(f"\nFAILED: the user position is `capped` with --strategy {strategy}")
                raise SystemExit(1)
    return rows


def main() -> None:
    """Run the chosen measurement and save the raw numbers."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="mode", required=True)
    for mode, help_text in (("pairs", "time diff against diff --new-values"), ("stress", "a request id on every line")):
        sub = commands.add_parser(mode, help=help_text)
        sub.add_argument("--no-save", action="store_true", help="do not write the raw numbers")
        if mode == "pairs":
            sub.add_argument("--size", type=int, default=100, help="size of the generated logs in MB (default 100)")
            sub.add_argument("--repeat", type=int, default=3)
        else:
            sub.add_argument("--lines", type=int, default=1_500_000, help="lines in each log")
    args = parser.parse_args()
    rows = pairs(args) if args.mode == "pairs" else stress(args)
    if not args.no_save:
        out = ROOT / "bench" / "results" / f"new-values-{args.mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
        print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
