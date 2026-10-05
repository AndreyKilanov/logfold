"""The adaptive strategy against the fixed ones: time and peak memory of `analyze --strategy auto|chunked|sequential`.

`auto` mines in parallel chunks unless the first chunk shows that almost every record opens a new template; then it mines
sequentially. On inputs of ordinary logs it must cost nothing (same strategy as `chunked`); on inputs of unique messages
it must not be slower and larger than the sequential strategy by much.

Every command runs as a separate process (see ``run.py``), the median of ``--repeat`` runs is stored in
``bench/results/adaptive.json``. Usage::

    python bench/tools/adaptive.py --repeat 3
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import tempfile
import time
from pathlib import Path

from run import CORES, ROOT, Sample, measure, summarize
from run import logfold as logfold_command

import logfold

DATA = ROOT / "bench" / "data"
FILES: dict[str, tuple[Path, int]] = {
    "highcard 10 MB": (DATA / "highcard_10mb.log", 8),
    "highcard 100 MB": (DATA / "highcard_100mb.log", 8),
    "highcard 100 MB (default chunk)": (DATA / "highcard_100mb.log", 64),
    "generated Loghub-like 100 MB": (DATA / "loghub_100mb.log", 8),
    "HDFS 1.6 GB": (DATA / "loghub2" / "hdfs.txt", 8),
    "BGL 0.7 GB": (DATA / "loghub2" / "bgl.txt", 8),
    "Spark 1.6 GB": (DATA / "loghub2" / "spark.txt", 8),
    "Thunderbird 0.9 GB": (DATA / "loghub2" / "thunderbird.txt", 8),
}
STRATEGIES = ("chunked", "auto", "sequential")


def command(path: Path, strategy: str, chunk_mb: int) -> list[str]:
    """The `analyze` command for one file and strategy."""
    base = ["analyze", str(path), "-f", "plain", "--top", "1", "-q", "--engine", "native", "--strategy", strategy]
    if strategy != "sequential":
        base += ["--threads", str(CORES), "--chunk-mb", str(chunk_mb)]
    return logfold_command(*base)


def chosen(path: Path, chunk_mb: int) -> str:
    """The strategy that `auto` ends up with, read from the metrics of one JSON run."""
    run = subprocess.run([*command(path, "auto", chunk_mb), "--json"], capture_output=True, text=True, check=True)
    return str(json.loads(run.stdout)["metrics"]["strategy"])


def prefix_ratios() -> dict[str, dict[str, float]]:
    """Templates per record after the first 10,000 records of every input, with and without masks."""
    out: dict[str, dict[str, float]] = {}
    with tempfile.TemporaryDirectory() as folder:
        for label, (path, _chunk) in FILES.items():
            if not path.exists() or label in out or "(default chunk)" in label:
                continue
            head = Path(folder) / "head.log"
            with path.open("rb") as source, head.open("wb") as target:
                for number, line in enumerate(source):
                    if number >= 10_000:
                        break
                    target.write(line)
            out[label] = {}
            for name, masks in (("masks", None), ("no masks", [])):
                result = logfold.analyze(head, format="plain", strategy="sequential", examples="none", masks=masks)
                out[label][name] = len(result.templates) / max(result.run.records, 1)
    return out


def sweep(lines: int = 700_000) -> dict[str, dict[str, float]]:
    """Time sequential and chunked mining of generated logs in which a share of the lines is unique."""
    words = [f"w{i}" for i in range(5000)]
    out: dict[str, dict[str, float]] = {}
    with tempfile.TemporaryDirectory() as folder:
        for share in (0.02, 0.1, 0.25, 0.5, 1.0):
            rng = random.Random(1)
            common = [" ".join(rng.choice(words) for _ in range(rng.randrange(4, 9))) for _ in range(300)]
            path = Path(folder) / f"share-{share}.log"
            with path.open("w", encoding="utf-8") as handle:
                for number in range(lines):
                    if rng.random() < share:
                        body = " ".join(rng.choice(words) for _ in range(rng.randrange(4, 9)))
                        handle.write(f"INFO svc{rng.randrange(10**9)} uniq{rng.randrange(10**9)} {body} end\n")
                    else:
                        handle.write(f"INFO svc1 {rng.choice(common)} id={number} end\n")
            out[str(share)] = {}
            for strategy in ("sequential", "chunked"):
                started = time.perf_counter()
                logfold.analyze(path, format="plain", strategy=strategy, chunk_bytes=8 << 20, examples="none", masks=[])
                out[str(share)][strategy] = time.perf_counter() - started
    return out


def main() -> None:
    """Measure every file with every strategy and store the medians."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out", type=Path, default=ROOT / "bench" / "results" / "adaptive.json")
    parser.add_argument("--extras-only", action="store_true", help="only the threshold evidence: prefix and sweep")
    args = parser.parse_args()
    if args.extras_only:
        data = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
        data["prefix_ratios"] = prefix_ratios()
        data["sweep"] = sweep()
        args.out.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: data[k] for k in ("prefix_ratios", "sweep")}, indent=1))
        return
    results: dict[str, object] = {"cores": CORES, "repeat": args.repeat, "files": {}}
    for label, (path, chunk_mb) in FILES.items():
        if not path.exists():
            print(f"skip {label}: {path} is missing")
            continue
        entry: dict[str, object] = {"chunk_mb": chunk_mb, "auto_chose": chosen(path, chunk_mb)}
        for strategy in STRATEGIES:
            samples: list[Sample] = [
                measure(command(path, strategy, chunk_mb), args.timeout) for _ in range(args.repeat)
            ]
            entry[strategy] = summarize(samples)
            print(f"{label:34} {strategy:10} {entry[strategy]}", flush=True)  # type: ignore[index]
        results["files"][label] = entry  # type: ignore[index]
    args.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
