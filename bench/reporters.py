"""Time and memory of the reporters on results with many templates, built in memory.

The reporters only read the public result model, so the results are made from a tiny real diff by replacing its template
lists with ``--sizes`` synthetic ones: most templates are new, a fifth changed or gone, about 18 percent of the new ones
WARN or ERROR. Each reporter runs with its default options (``default``) and with every template asked for (``all``).
The four pipeline reporters hand the columns of the result to the Rust core, so their time includes building the columns;
``csv``, ``json`` and ``markdown`` are written in Python. The best of
``--repeat`` runs is the time; ``tracemalloc`` gives the peak of the Python allocations of one more run (the memory of the
Rust side is not in it)::

    python bench/reporters.py --sizes 5000 20000 100000
    python bench/reporters.py --reporter junit prometheus --repeat 5

``csv``, ``json`` and ``markdown`` are in the default list for scale: they are Python reporters that already write every
template.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
import tempfile
import time
import tracemalloc
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from functools import partial
from hashlib import sha256
from pathlib import Path

import logfold
from logfold import _bridge
from logfold.ext import registry
from logfold.model import AnalysisResult, DiffEntry, DiffResult, Template

DEFAULT_REPORTERS = ["csv", "json", "markdown", "github-summary", "junit", "chat-message", "prometheus"]
UNLIMITED = 1 << 40
MOMENT = datetime(2026, 10, 4, 12, 0, 0)


def template_texts(rng: random.Random, count: int) -> list[str]:
    """Templates like the ones of a real diff: a service, a few words and placeholders."""
    words = [f"word{i}" for i in range(3000)]
    return [
        " ".join(
            [f"svc{rng.randrange(count // 4 + 1)}", *(rng.choice(words) for _ in range(rng.randrange(3, 9))), "<NUM>"]
        )
        for _ in range(count)
    ]


def synthetic_results(size: int) -> tuple[AnalysisResult, DiffResult]:
    """Return an analysis and a diff that hold ``size`` templates."""
    with tempfile.TemporaryDirectory() as folder:
        before, after = Path(folder) / "a.log", Path(folder) / "b.log"
        before.write_text("2026-10-04T12:00:00Z INFO a" + chr(10), encoding="utf-8")
        after.write_text("2026-10-04T12:00:00Z INFO b" + chr(10), encoding="utf-8")
        diff_base = logfold.diff(before, after, format="app")
        analysis_base = logfold.analyze(before, format="app")
    rng = random.Random(size)
    texts = template_texts(rng, size)
    levels = [rng.choice(["ERROR", "WARN"] + ["INFO"] * 4 + ["DEBUG"] * 5) for _ in texts]
    counts = [rng.randrange(1, 5000) for _ in texts]
    entries = [
        DiffEntry(
            sha256(text.encode()).hexdigest()[:16],
            text,
            0,
            count,
            0.0,
            count / size,
            None,
            level,
            {level: count},
            text,
            MOMENT,
            MOMENT,
            1.0 + count,
            0.001,
        )
        for text, count, level in zip(texts, counts, levels, strict=True)
    ]
    entries.sort(key=lambda entry: -entry.after_count)
    fifth = size // 5
    diff = replace(
        diff_base,
        new_templates=tuple(entries[: size - 2 * fifth]),
        changed=tuple(replace(e, before_count=e.after_count // 3, ratio=3.0) for e in entries[-2 * fifth : -fifth]),
        disappeared=tuple(replace(e, before_count=e.after_count, after_count=0) for e in entries[-fifth:]),
        unchanged=size,
    )
    templates = tuple(Template(e.id, e.text, e.after_count, MOMENT, MOMENT, e.text, e.level, e.levels) for e in entries)
    return replace(analysis_base, templates=templates), diff


def measure(render: Callable[[], str], repeat: int) -> tuple[float, int, int]:
    """Return the best time, the peak Python memory and the length of one rendering."""
    best, text = math.inf, ""
    for _ in range(repeat):
        started = time.perf_counter()
        text = render()
        best = min(best, time.perf_counter() - started)
    tracemalloc.start()
    render()
    peak = tracemalloc.get_traced_memory()[1]
    tracemalloc.stop()
    return best, peak, len(text.encode("utf-8"))


def main() -> None:
    """Print one Markdown table of the measurements."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sizes", nargs="+", type=int, default=[5000, 20000, 100000], help="templates per result")
    parser.add_argument("--reporter", nargs="+", default=DEFAULT_REPORTERS, help="reporters to time")
    parser.add_argument("--repeat", type=int, default=3, help="runs per cell; the best is shown")
    args = parser.parse_args()
    if not _bridge.is_available():
        sys.exit("the native extension is not built: run `maturin develop --release`")
    print("| templates | result | reporter | rows | time | Python memory | output |")
    print("|---:|---|---|---|---:|---:|---:|")
    for size in args.sizes:
        analysis, diff = synthetic_results(size)
        for kind, result in (("analysis", analysis), ("diff", diff)):
            for name in args.reporter:
                reporter = registry.get_reporter(name)
                if kind not in reporter.kinds:
                    continue
                for rows in ("default", "all"):
                    options = {} if rows == "default" else {"top": size, "max_bytes": UNLIMITED, "max_chars": UNLIMITED}
                    seconds, peak, length = measure(partial(reporter.render, result, **options), args.repeat)
                    print(
                        f"| {size:,} | {kind} | {name} | {rows} | {seconds * 1000:,.0f} ms "
                        f"| {peak / 1e6:,.1f} MB | {length / 1e6:,.2f} MB |",
                        flush=True,
                    )


if __name__ == "__main__":
    main()
