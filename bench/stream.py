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
"""

from __future__ import annotations

import argparse
import itertools
import statistics
import sys
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
    inner = sub.add_parser("worker", help="(internal) mine a file in this process")
    inner.add_argument("name", choices=VARIANTS)
    inner.add_argument("path", type=Path)
    inner.add_argument("--batch-size", type=int, default=10_000)
    args = main_parser.parse_args()
    if args.what == "run":
        run(args)
    else:
        worker(args.name, args.path, args.batch_size)


if __name__ == "__main__":
    main()
