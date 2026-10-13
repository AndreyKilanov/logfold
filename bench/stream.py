"""Speed of mining a log through the streaming interfaces, against ``analyze`` and Drain3.

Every variant mines the same file in its own process, standard output discarded, and the table gives wall time, CPU time
and peak memory (median of ``--repeat`` runs), the same way ``speed.py`` measures. Parameters are aligned: depth 4,
similarity threshold 0.4, the default masks, plain text, no examples.

Variants: ``analyze`` (the sequential strategy, the reference), ``stream`` (``logfold stream FILE``), ``add_many`` and
``add_lines`` (``logfold.Miner`` fed in batches), ``add_log_message`` (one native call per record) and ``drain3`` (one
``add_log_message`` per record, slow: use a small file).

Usage::

    python bench/stream.py run bench/data/app_100mb.log --variants analyze stream add_many add_lines add_log_message
    python bench/stream.py run bench/data/app_10mb.log --variants analyze add_many drain3
    python bench/stream.py parallel bench/data/app_100mb.log --workers 4
    python bench/stream.py matching bench/data/app_100mb.log
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import speed

VARIANTS = ("analyze", "stream", "add_many", "add_lines", "add_log_message", "drain3")


def lines(path: Path) -> Iterator[str]:
    """The lines of the file without their line feeds."""
    with open(path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            yield line.rstrip("\n")


def batches(items: Iterator[str], size: int) -> Iterator[list[str]]:
    """Cut an iterator into lists of ``size`` items."""
    while batch := list(itertools.islice(items, size)):
        yield batch


def worker(name: str, path: Path, batch_size: int) -> None:
    """Mine ``path`` with one of the library variants; runs in its own process."""
    if name == "drain3":
        speed.drain3(argparse.Namespace(path=path, masks="default"))
        return
    import logfold

    miner = logfold.Miner(format="plain", examples="none")
    if name == "add_many":
        for batch in batches(lines(path), batch_size):
            miner.add_many(batch)
    elif name == "add_lines":
        with open(path, encoding="utf-8", errors="replace") as stream:
            while batch := list(itertools.islice(stream, batch_size)):
                miner.add_lines(batch)
        miner.flush()
    else:
        for line in lines(path):
            miner.add_log_message(line)
    miner.result()


def command(name: str, path: Path, batch_size: int) -> list[str]:
    """The command line that measures one variant."""
    if name == "analyze":
        return speed.logfold(
            "analyze", str(path), "-f", "plain", "--strategy", "sequential", "--examples", "none", "--json", "-q"
        )
    if name == "stream":
        return speed.logfold(
            "stream", str(path), "-f", "plain", "--examples", "none", "--json", "-q", "--batch-size", str(batch_size)
        )
    return [sys.executable, str(Path(__file__).resolve()), "worker", name, str(path), "--batch-size", str(batch_size)]


def run(args: argparse.Namespace) -> None:
    """Measure the chosen variants on one file and print a Markdown table."""
    size = args.path.stat().st_size
    print(f"\n{args.path.name}, {size / 1e6:.0f} MB, batch {args.batch_size}, median of {args.repeat}\n")
    print("| variant | wall | speed | CPU | peak memory | against analyze |")
    print("|---|---|---|---|---|---|")
    reference = None
    for name in args.variants:
        samples = [speed.measure(command(name, args.path, args.batch_size), args.timeout) for _ in range(args.repeat)]
        if any(sample.returncode != 0 for sample in samples):
            print(f"| {name} | failed (exit code {[s.returncode for s in samples]}) | | | | |")
            continue
        wall = statistics.median(s.wall_s for s in samples)
        reference = wall if name == "analyze" else reference
        ratio = f"{wall / reference:.2f}x" if reference else ""
        print(
            f"| {name} | {wall:.2f} s | {size / 1e6 / wall:,.0f} MB/s | {statistics.median(s.cpu_s for s in samples):.1f} s | "
            f"{max(s.peak_mb for s in samples):,.0f} MB | {ratio} |",
            flush=True,
        )


def feed(miner: object, items: list[str], batch_size: int) -> None:
    """Give ``items`` to a ``logfold.Miner`` in batches."""
    for start in range(0, len(items), batch_size):
        miner.add_many(items[start : start + batch_size])  # type: ignore[attr-defined]


def timed(workers: list[tuple[object, list[str]]], batch_size: int) -> float:
    """Wall time of feeding every ``(miner, lines)`` pair from its own thread."""
    threads = [threading.Thread(target=feed, args=(miner, items, batch_size)) for miner, items in workers]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return time.perf_counter() - started


def parallel(args: argparse.Namespace) -> None:
    """Compare one miner, several miners (one per source) and one shared miner, fed from threads of one process."""
    import logfold

    lines_read = list(itertools.islice(lines(args.path), args.lines))
    parts = [lines_read[index :: args.workers] for index in range(args.workers)]

    def miner() -> logfold.Miner:
        return logfold.Miner(format="plain", examples="none")

    cases = {
        "1 miner, 1 thread": lambda: timed([(miner(), lines_read)], args.batch_size),
        f"{args.workers} miners, {args.workers} threads (one per source)": lambda: timed(
            [(miner(), part) for part in parts], args.batch_size
        ),
        f"1 shared miner, {args.workers} threads": lambda: timed(
            [(shared, part) for shared in [miner()] for part in parts], args.batch_size
        ),
    }
    print(f"{args.path.name}, the first {len(lines_read):,} lines, batch {args.batch_size}, median of {args.repeat}")
    print()
    print("| case | wall | lines per second | against 1 miner |")
    print("|---|---:|---:|---:|")
    reference = None
    for label, case in cases.items():
        wall = statistics.median(case() for _ in range(args.repeat))
        reference = reference or wall
        print(f"| {label} | {wall:.2f} s | {len(lines_read) / wall:,.0f} | {reference / wall:.2f}x |", flush=True)


def matching(args: argparse.Namespace) -> None:
    """Time ``match_many`` and ``match`` on a trained miner, against ``add_many`` of the same lines."""
    import logfold

    lines_read = list(itertools.islice(lines(args.path), args.lines))
    trained = logfold.Miner(format="plain", examples="none")
    trained.add_many(lines_read[: args.train])

    def by_batches(size: int, exact: bool = False) -> float:
        started = time.perf_counter()
        for start in range(0, len(lines_read), size):
            trained.match_many(lines_read[start : start + size], exact=exact)
        return time.perf_counter() - started

    def one_by_one() -> float:
        started = time.perf_counter()
        for line in lines_read:
            trained.match(line)
        return time.perf_counter() - started

    def mining() -> float:
        miner = logfold.Miner(format="plain", examples="none")
        started = time.perf_counter()
        feed(miner, lines_read, args.batch_size)
        return time.perf_counter() - started

    cases = {f"match_many, batches of {size:,}": (lambda size=size: by_batches(size)) for size in (100, 1_000, 10_000)}
    cases["match_many exact, batches of 10,000"] = lambda: by_batches(10_000, exact=True)
    cases["match, one record per call"] = one_by_one
    cases[f"add_many, batches of {args.batch_size:,} (mining the same lines)"] = mining
    print(f"{args.path.name}, {len(lines_read):,} lines, trained on the first {args.train:,}, median of {args.repeat}")
    print()
    print("| case | wall | lines per second | against match_many 10,000 |")
    print("|---|---:|---:|---:|")
    walls = {label: statistics.median(case() for _ in range(args.repeat)) for label, case in cases.items()}
    reference = walls["match_many, batches of 10,000"]
    for label, wall in walls.items():
        print(f"| {label} | {wall:.2f} s | {len(lines_read) / wall:,.0f} | {wall / reference:.2f}x |")


def main() -> None:
    """The command line."""
    main_parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = main_parser.add_subparsers(dest="what", required=True)
    measuring = sub.add_parser("run", help="measure the variants on a file")
    measuring.add_argument("path", type=Path)
    measuring.add_argument("--variants", nargs="+", choices=VARIANTS, default=list(VARIANTS[:5]))
    measuring.add_argument("--repeat", type=int, default=3)
    measuring.add_argument("--batch-size", type=int, default=10_000)
    measuring.add_argument("--timeout", type=float, default=900.0)
    threads = sub.add_parser("parallel", help="one miner, one miner per source and one shared miner, from threads")
    threads.add_argument("path", type=Path)
    threads.add_argument("--lines", type=int, default=600_000)
    threads.add_argument("--workers", type=int, default=4)
    threads.add_argument("--repeat", type=int, default=5)
    threads.add_argument("--batch-size", type=int, default=10_000)
    matched = sub.add_parser("matching", help="match_many and match on a trained miner, against add_many")
    matched.add_argument("path", type=Path)
    matched.add_argument("--lines", type=int, default=600_000)
    matched.add_argument("--train", type=int, default=100_000)
    matched.add_argument("--repeat", type=int, default=5)
    matched.add_argument("--batch-size", type=int, default=10_000)
    inner = sub.add_parser("worker", help="(internal) mine a file in this process")
    inner.add_argument("name", choices=VARIANTS)
    inner.add_argument("path", type=Path)
    inner.add_argument("--batch-size", type=int, default=10_000)
    args = main_parser.parse_args()
    if args.what == "run":
        run(args)
    elif args.what == "parallel":
        parallel(args)
    elif args.what == "matching":
        matching(args)
    else:
        worker(args.name, args.path, args.batch_size)


if __name__ == "__main__":
    main()
