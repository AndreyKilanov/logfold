"""How the time of `analyze` result building and of `diff` grows with the number of templates.

Large inputs are slow to measure, so the script runs three or four small sizes (a few thousand templates each), fits the
growth exponent ``t ~ n^k`` between the smallest and the largest and extrapolates to bigger results. A matcher whose
projected time exceeds the budget is skipped at the larger sizes.

Usage::

    python bench/diff_scale.py --sizes 5000 10000 20000 --out bench/results/diff-scale.json
"""

from __future__ import annotations

import argparse
import json
import math
import random
import tempfile
import time
from pathlib import Path

import logfold

MATCHERS = ("exact", "token_subset", "jaccard")
PROJECT_TO = (54_000, 100_000)


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


def exponent(rows: list[dict[str, float | int | None]], key: str) -> float | None:
    """Fit ``t ~ n^k`` between the first and the last size that has a time for ``key``."""
    timed = [(float(r["templates"] or 0), float(r[key] or 0)) for r in rows if r.get(key)]
    if len(timed) < 2 or timed[0][1] <= 0:
        return None
    (n1, t1), (n2, t2) = timed[0], timed[-1]
    return math.log(t2 / t1) / math.log(n2 / n1)


def project(rows: list[dict[str, float | int | None]], key: str, templates: int) -> float | None:
    """Extrapolate the time of ``key`` to ``templates`` templates with the fitted exponent."""
    k = exponent(rows, key)
    timed = [r for r in rows if r.get(key)]
    if k is None or not timed:
        return None
    last = timed[-1]
    return float(last[key] or 0) * (templates / float(last["templates"] or 1)) ** k


def markdown(rows: list[dict[str, float | int | None]]) -> str:
    """Render the measurements, exponents and projections as Markdown tables."""
    keys = ["analyze_s", "analyze_engine_s", *(f"diff_{m}_s" for m in MATCHERS)]

    def cell(value: float | int | None) -> str:
        return "skipped" if value is None else f"{value:,.2f}"

    lines = ["| lines | templates | " + " | ".join(keys) + " |", "|---:|---:|" + "---:|" * len(keys)]
    for row in rows:
        lines.append(
            f"| {row['lines']:,} | {row['templates']:,} | " + " | ".join(cell(row.get(k)) for k in keys) + " |"
        )
    lines += [
        "",
        "| measure | growth exponent | " + " | ".join(f"projected at {n:,} templates (s)" for n in PROJECT_TO) + " |",
    ]
    lines.append("|---|---:|" + "---:|" * len(PROJECT_TO))
    for key in keys:
        k = exponent(rows, key)
        if k is None:
            continue
        projected = [project(rows, key, n) for n in PROJECT_TO]
        lines.append(f"| {key} | {k:.2f} | " + " | ".join(cell(p) for p in projected) + " |")
    return "\n".join(lines)


def main() -> None:
    """Run the measurements and print or save them."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", type=int, nargs="+", default=[5000, 10000, 20000], help="lines per run")
    parser.add_argument("--repeat", type=int, default=3, help="repeats of the fast measurements")
    parser.add_argument("--budget", type=float, default=120.0, help="skip a matcher when 4x its last time exceeds this")
    parser.add_argument("--out", type=Path, help="write the rows as JSON")
    args = parser.parse_args()
    rows: list[dict[str, float | int | None]] = []
    previous: dict[str, float] = {}
    for lines in args.sizes:
        rows.append(measure(lines, args.repeat, args.budget, previous))
        print(f"done {lines:,} lines", flush=True)
    print()
    print(markdown(rows))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps({"logfold": logfold.__version__, "rows": rows}, indent=2) + "\n", encoding="utf-8"
        )


if __name__ == "__main__":
    main()
