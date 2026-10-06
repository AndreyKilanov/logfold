"""Time of the native diff matchers on 5, 20 and 100 thousand one-sided templates.

A matcher only sees the templates that occur in one run, so the input is two lists of templates. Two shapes are
generated, both seeded: ``sparse`` (a vocabulary of 3000 words, few templates share a word) and ``dense`` (300 words,
many candidate pairs). Every matcher runs in the Rust core through ``native.match_templates``; the best of ``--repeat``
runs is reported, with the number of pairs found and the growth exponent ``t ~ n^k`` between the smallest and the
largest size. Results go to ``bench/results/matcher-scale.json``; the discussion is in ``bench/docs/diff/DIFF_MATCHERS.md``.
Usage::

    python bench/tools/matcher_scale.py --sizes 5000 20000 100000
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

from logfold.engines import native

ROOT = Path(__file__).resolve().parents[2]
SHAPES = {"sparse": 3000, "dense": 300}
MATCHERS: dict[str, tuple[str, float | None]] = {
    "jaccard": ("jaccard", 0.6),
    "jaccard-idf": ("jaccard_idf", 0.5),
    "overlap": ("overlap", 0.8),
    "rules": ("rules", None),
}


def templates(rng: random.Random, count: int, vocabulary: int) -> list[str]:
    """Templates like the one-sided templates of a diff: a level, a service, a few words."""
    words = [f"w{i}" for i in range(vocabulary)]
    return [
        " ".join(["INFO", f"svc{rng.randrange(count // 4)}", *(rng.choice(words) for _ in range(rng.randrange(3, 9)))])
        for _ in range(count)
    ]


def timed(
    kind: str, threshold: float | None, rules: list[tuple[str, str]], before: list[str], after: list[str]
) -> tuple[float, int]:
    started = time.perf_counter()
    pairs = native.match_templates(kind, before, after, threshold, rules if kind == "rules" else None)
    return time.perf_counter() - started, len(pairs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="*", type=int, default=[5000, 20000, 100000])
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--out", type=Path, default=ROOT / "bench" / "results" / "matcher-scale.json")
    args = parser.parse_args()
    rows: list[dict[str, object]] = []
    for shape, vocabulary in SHAPES.items():
        for size in args.sizes:
            rng = random.Random(size)
            before, after = templates(rng, size, vocabulary), templates(rng, size, vocabulary)
            rules = [(before[i], after[i]) for i in range(0, size, max(size // 2000, 1))]
            for name, (kind, threshold) in MATCHERS.items():
                runs = [timed(kind, threshold, rules, before, after) for _ in range(args.repeat)]
                seconds = min(run[0] for run in runs)
                rows.append({"shape": shape, "size": size, "matcher": name, "seconds": seconds, "pairs": runs[0][1]})
                print(f"{shape:7} {size:7} {name:12} {seconds:8.3f} s  {runs[0][1]:7} pairs", flush=True)
    for shape in SHAPES:
        for name in MATCHERS:
            series = [r for r in rows if r["shape"] == shape and r["matcher"] == name]
            first, last = series[0], series[-1]
            if first["seconds"] and last["size"] != first["size"]:
                exponent = math.log(float(last["seconds"]) / float(first["seconds"])) / math.log(
                    int(last["size"]) / int(first["size"])
                )  # type: ignore[arg-type]
                print(f"growth {shape:7} {name:12} k = {exponent:.2f}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"sizes": args.sizes, "runs": rows}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
