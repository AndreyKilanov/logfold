"""Record how many templates each tool finds on each dataset (the "equivalence of work" check of the protocol).

Usage::

    python bench/equivalence.py --out bench/results/templates.json
"""

from __future__ import annotations

import argparse
import csv
import glob
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable


def run(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", check=False)
    return result.stdout


def logfold_count(path: Path, masked: bool) -> int:
    import logfold

    masks = None if masked else []
    return len(logfold.analyze(str(path), format="plain", masks=masks, examples="none").templates)


def drain3_count(path: Path, masked: bool) -> int:
    out = run(
        [
            PYTHON,
            str(ROOT / "bench" / "competitors" / "drain3_run.py"),
            str(path),
            "--masks",
            "default" if masked else "none",
        ]
    )
    match = re.search(r"templates=(\d+)", out)
    return int(match.group(1)) if match else -1


def logdrain_count(path: Path, masked: bool) -> int:
    exe = shutil.which("logdrain")
    if not exe:
        return -1
    flags = ["--format", "csv", "--sim-th", "0.4", "--depth", "4"] + (["--masks", "uuid,hex32,ipv4"] if masked else [])
    rows = list(csv.reader(io.StringIO(run([exe, str(path), *flags]))))
    return max(len(rows) - 1, 0)


def logdelta_count(path: Path) -> int:
    exe = shutil.which("logdelta")
    if not exe:
        return -1
    out = run([exe, "templates", str(path), "--threshold", "0.4", "--json", "-n", "1000000"])
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return -1
    if isinstance(data, dict):
        for key in ("clusters", "templates", "items"):
            value = data.get(key)
            if isinstance(value, list):
                return len(value)
            if isinstance(value, int):
                return value
    return len(data) if isinstance(data, list) else -1


def expand(patterns: list[Path]) -> list[Path]:
    """Expand wildcards in file arguments (PowerShell and cmd leave them to the program)."""
    files: list[Path] = []
    for pattern in patterns:
        matches = sorted(glob.glob(str(pattern)))
        files += [Path(m) for m in matches] if matches else [pattern]
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "bench" / "data")
    parser.add_argument("--datasets", nargs="*", default=None, help="generated datasets, default: the four 100 MB sets")
    parser.add_argument("--files", nargs="*", type=Path, default=[], help="your own log files")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.files = expand(args.files)
    names = (
        args.datasets
        if args.datasets is not None
        else ([] if args.files else ["nginx_100mb", "app_100mb", "loghub_100mb", "highcard_10mb"])
    )
    inputs = [(name, args.data / f"{name}.log") for name in names] + [
        (f"real:{file.stem}", file) for file in args.files
    ]
    table: dict[str, dict[str, int]] = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for name, path in inputs:
        row = {
            "logfold (no masks)": logfold_count(path, masked=False),
            "Drain3 (no masks)": drain3_count(path, masked=False),
            "logdrain (no masks)": logdrain_count(path, masked=False),
            "logfold (masks)": logfold_count(path, masked=True),
            "Drain3 (masks)": drain3_count(path, masked=True),
            "logdrain (masks)": logdrain_count(path, masked=True),
            "logdelta (built-in masks)": logdelta_count(path),
        }
        table[name] = row
        print(name, row, flush=True)
        args.out.write_text(json.dumps(table, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
