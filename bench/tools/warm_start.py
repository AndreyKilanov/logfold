"""The warm start of the chunked strategy: stray templates, time and peak memory against the cold start.

With ``--warm-start`` the first chunk is trained alone and every other chunk starts from a copy of its tree. The script
runs every input with the cold start, the warm start and the sequential strategy and stores the number of templates (one
run each), and the median wall time and the peak working set of three runs of ``logfold analyze`` (see ``run.py``).
Results go to ``bench/results/warm-start.json``; the discussion is in ``bench/docs/engine/WARM_START.md``. Usage::

    python bench/tools/warm_start.py --repeat 3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from run import CORES, ROOT, Sample, measure, summarize
from run import logfold as logfold_command

import logfold

DATA = ROOT / "bench" / "data"
INPUTS: dict[str, tuple[Path, bool]] = {
    "HDFS, no masks": (DATA / "loghub2" / "hdfs.txt", False),
    "Spark, no masks": (DATA / "loghub2" / "spark.txt", False),
    "Thunderbird, no masks": (DATA / "loghub2" / "thunderbird.txt", False),
    "Thunderbird": (DATA / "loghub2" / "thunderbird.txt", True),
    "Spark": (DATA / "loghub2" / "spark.txt", True),
    "BGL": (DATA / "loghub2" / "bgl.txt", True),
    "generated Loghub-like": (DATA / "loghub_100mb.log", True),
}
CHUNKS_MB = (8, 64)


def command(path: Path, masked: bool, chunk_mb: int, warm: bool) -> list[str]:
    """The `analyze` command of one configuration."""
    args = ["analyze", str(path), "-f", "plain", "--top", "1", "-q", "--engine", "native"]
    args += ["--strategy", "chunked", "--threads", str(CORES), "--chunk-mb", str(chunk_mb)]
    if not masked:
        args.append("--no-masks")
    if warm:
        args.append("--warm-start")
    return logfold_command(*args)


def templates(path: Path, masked: bool, strategy: str, chunk_mb: int, warm: bool) -> int:
    """Number of templates of one configuration (one run)."""
    result = logfold.analyze(
        path,
        format="plain",
        strategy=strategy,
        chunk_bytes=chunk_mb << 20,
        warm_start=warm,
        examples="none",
        masks=None if masked else [],
    )
    return len(result.templates)


def main() -> None:
    """Measure every input with every configuration and store the results."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--out", type=Path, default=ROOT / "bench" / "results" / "warm-start.json")
    args = parser.parse_args()
    results: dict[str, object] = {"cores": CORES, "repeat": args.repeat, "inputs": {}}
    for label, (path, masked) in INPUTS.items():
        if not path.exists():
            print(f"skip {label}: {path} is missing")
            continue
        entry: dict[str, object] = {"sequential_templates": templates(path, masked, "sequential", 64, False)}
        for chunk_mb in CHUNKS_MB:
            row: dict[str, object] = {}
            for warm in (False, True):
                name = "warm" if warm else "cold"
                samples: list[Sample] = [
                    measure(command(path, masked, chunk_mb, warm), args.timeout) for _ in range(args.repeat)
                ]
                summary = summarize(samples)
                row[name] = {
                    "templates": templates(path, masked, "chunked", chunk_mb, warm),
                    "wall_median_s": summary["wall_median_s"],
                    "peak_mb": summary["peak_mb_max"],
                }
                print(f"{label:24} {chunk_mb:3} MiB {name}: {row[name]}", flush=True)
            entry[f"chunk_{chunk_mb}_mib"] = row
        results["inputs"][label] = entry  # type: ignore[index]
    args.out.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
