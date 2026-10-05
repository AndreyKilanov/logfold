"""How the time of `analyze` result building and of `diff` grows with the number of templates.

Large inputs are slow to measure, so the script runs a few small sizes (thousands of templates each); ``report.py`` fits
the growth exponent ``t ~ n^k`` between the smallest and the largest and extrapolates to bigger results. A matcher whose
projected time exceeds the budget is skipped at the larger sizes.

Each run is stored as a *stage* (a name for the state of the code, for example ``before`` or ``native``) in
``bench/results/diff-scale.json``; ``python bench/tools/report.py`` turns the stages into a section of
``bench/RESULTS.md``.

Usage::

    python bench/tools/diff_scale.py --stage native --sizes 5000 10000 20000 40000 80000
"""

from __future__ import annotations

import argparse
import json
import math
import random
import tempfile
import time
from pathlib import Path

from report import diff_scale_table

import logfold

ROOT = Path(__file__).resolve().parents[2]
MATCHERS = ("exact", "token_subset", "jaccard")


def write_log(path: Path, lines: int, seed: int) -> None:
    """Write a deterministic log whose number of templates is about 0.9 times the number of lines."""
    rng = random.Random(seed)
    words = [f"w{i}" for i in range(3000)]
    shapes = max(lines // 4, 1)
    with path.open("w", encoding="utf-8") as handle:
        for i in range(lines):
            shape = rng.randrange(shapes)
            body = " ".join(rng.choice(words) for _ in range(rng.randrange(3, 9)))
            handle.write(
                f"2026-10-04T12:{i // 60 % 60:02d}:{i % 60:02d}Z INFO svc{shape} {body} op{shape % 977} done\n"
            )


def best_of(repeat: int, action):  # type: ignore[no-untyped-def]
    """Return the shortest wall time of ``repeat`` runs and the last result."""
    best = math.inf
    value = None
    for _ in range(repeat):
        started = time.perf_counter()
        value = action()
        best = min(best, time.perf_counter() - started)
    return best, value


def measure(lines: int, repeat: int, budget: float, previous: dict[str, float]) -> dict[str, float | int | None]:
    """Measure one size; ``previous`` holds the times of the smaller size and is updated."""
    with tempfile.TemporaryDirectory() as folder:
        first, second = Path(folder) / "before.log", Path(folder) / "after.log"
        write_log(first, lines, 1)
        write_log(second, lines, 2)

        def analyze(path: Path) -> logfold.AnalysisResult:
            return logfold.analyze(str(path), format="app", threads=1, strategy="sequential")

        total, before = best_of(repeat, lambda: analyze(first))
        after = analyze(second)
        row: dict[str, float | int | None] = {
            "lines": lines,
            "templates": len(before.templates),
            "analyze_s": total,
            "analyze_engine_s": before.metrics.wall_total_s,
        }
        for matcher in MATCHERS:
            key = f"diff_{matcher}_s"
            if previous.get(key, 0.0) * 4 > budget:
                row[key] = None
                continue
            seconds, _ = best_of(
                1 if previous.get(key, 0.0) > 5 else repeat, lambda m=matcher: logfold.diff(before, after, matcher=m)
            )
            row[key] = seconds
            previous[key] = seconds
        return row


def main() -> None:
    """Run the measurements, print them and store them as a stage."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stage", required=True, help="name of the state of the code, for example before or native")
    parser.add_argument("--sizes", type=int, nargs="+", default=[5000, 10000, 20000], help="lines per run")
    parser.add_argument("--repeat", type=int, default=3, help="repeats of the fast measurements")
    parser.add_argument("--budget", type=float, default=120.0, help="skip a matcher when 4x its last time exceeds this")
    parser.add_argument("--out", type=Path, default=ROOT / "bench" / "results" / "diff-scale.json")
    parser.add_argument("--no-save", action="store_true", help="print only")
    args = parser.parse_args()
    rows: list[dict[str, float | int | None]] = []
    previous: dict[str, float] = {}
    for lines in args.sizes:
        rows.append(measure(lines, args.repeat, args.budget, previous))
        print(f"done {lines:,} lines", flush=True)
    print()
    print("\n".join(diff_scale_table(rows)))
    if not args.no_save:
        data = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {"stages": {}}
        data["stages"][args.stage] = {"logfold": logfold.__version__, "rows": rows}
        args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(f"stored stage {args.stage!r} in {args.out}")


if __name__ == "__main__":
    main()
