"""Compare the parallel resume of a saved state with the sequential one, on 100 MB logs.

For each file the first 30 percent of the bytes (cut at a line) are mined sequentially and saved as a state; the other 70
percent are then continued from that state twice: sequentially (the reference) and in parallel (the chunks start from a
copy of the loaded tree). The table shows the time of each, the templates, how many records sit in templates that both
found, and how many templates the parallel run has that the sequential one does not.

Usage::

    python bench/state_parallel.py FILE [FILE ...] [--chunk-mb 8] [--threads N]
"""

from __future__ import annotations

import argparse
import tempfile
import time
from pathlib import Path

import logfold


def split(path: Path, directory: Path) -> tuple[Path, Path]:
    data = path.read_bytes()
    cut = data.rfind(b"\n", 0, int(len(data) * 0.3)) + 1
    first, second = directory / "first.log", directory / "second.log"
    first.write_bytes(data[:cut])
    second.write_bytes(data[cut:])
    return first, second


def run(
    path: Path, *, strategy: str, state: Path, chunk_mb: int, threads: int | None
) -> tuple[logfold.AnalysisResult, float]:
    started = time.perf_counter()
    result = logfold.analyze(
        str(path), format="plain", strategy=strategy, chunk_bytes=chunk_mb << 20, threads=threads, load_state=state
    )
    return result, time.perf_counter() - started


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("files", nargs="+", type=Path)
    parser.add_argument("--chunk-mb", type=int, default=8)
    parser.add_argument("--threads", type=int, default=None)
    args = parser.parse_args()
    print(
        "| input | state templates | sequential: time, templates | parallel: time, templates | records in shared templates | extra templates |"
    )
    print("|---|---:|---|---|---:|---:|")
    for path in args.files:
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            first, second = split(path, directory)
            state = directory / "state.bin"
            seeded = logfold.analyze(
                str(first), format="plain", strategy="sequential", save_state=state, state_format="binary"
            )
            sequential, seconds_sequential = run(
                second, strategy="sequential", state=state, chunk_mb=args.chunk_mb, threads=args.threads
            )
            parallel, seconds_parallel = run(
                second, strategy="chunked", state=state, chunk_mb=args.chunk_mb, threads=args.threads
            )
            wanted = {t.text: t.count for t in sequential.templates}
            found = {t.text for t in parallel.templates}
            records = sum(wanted.values())
            shared = sum(count for text, count in wanted.items() if text in found)
            extra = len(found - set(wanted))
            print(
                f"| {path.name} | {len(seeded.templates):,} | {seconds_sequential:.1f} s, {len(sequential.templates):,} | "
                f"{seconds_parallel:.1f} s, {len(parallel.templates):,} | {100 * shared / records:.2f}% | {extra:,} |"
            )


if __name__ == "__main__":
    main()
