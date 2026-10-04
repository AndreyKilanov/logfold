"""Render ``bench/results/results.json`` as Markdown tables (``bench/RESULTS.md``).

Usage::

    python bench/report.py [results.json]
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def default_results() -> list[Path]:
    path = ROOT / "bench" / "results" / "results.json"
    if not path.exists():
        raise SystemExit("no results found; run bench/run.py first")
    return [path]


def fmt_time(run: dict[str, object]) -> str:
    if run.get("failed"):
        runs = run.get("runs", [])
        if isinstance(runs, list) and runs and runs[0].get("returncode") == -9:
            return "timeout"
        return "failed"
    return f"{run['wall_median_s']:.2f}"


def table(
    runs: list[dict[str, object]], scenario: str, datasets: list[str], peaks: dict[tuple[str, str], float]
) -> list[str]:
    rows: dict[str, dict[str, dict[str, object]]] = defaultdict(dict)
    sizes: dict[str, int] = {}
    for run in runs:
        if run["scenario"] != scenario:
            continue
        rows[str(run["tool"])][str(run["dataset"])] = run
        sizes[str(run["dataset"])] = int(run["input_bytes"])  # type: ignore[call-overload]
    present = [d for d in datasets if d in sizes]
    if not present:
        return []
    header = "| tool | " + " | ".join(f"{d} s (MB/s)" for d in present) + " | peak MB (max over all runs) |"
    lines = [header, "|---|" + "---:|" * (len(present) + 1)]
    best: dict[str, float] = {}
    for dataset in present:
        times = [
            float(r[dataset]["wall_median_s"])  # type: ignore[arg-type]
            for r in rows.values()
            if dataset in r and not r[dataset].get("failed")
        ]
        best[dataset] = min(times) if times else 0.0
    for tool, by_dataset in rows.items():
        cells = []
        for dataset in present:
            run = by_dataset.get(dataset)
            if run is None:
                cells.append("-")
                continue
            text = fmt_time(run)
            if not run.get("failed"):
                seconds = float(run["wall_median_s"])  # type: ignore[arg-type]
                throughput = sizes[dataset] / 1e6 / seconds
                text = f"{seconds:.2f} ({throughput:,.0f})"
                if seconds == best[dataset]:
                    text = f"**{text}**"
            cells.append(text)
        peak_value = peaks.get(("", tool.replace(" diff", "").split(",")[0]))
        peak = f"{peak_value:,.0f}" if peak_value else "-"
        lines.append(f"| {tool} | " + " | ".join(cells) + f" | {peak} |")
    return lines


def main() -> None:
    paths = [Path(arg) for arg in sys.argv[1:]] or default_results()
    parts = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    env = parts[0]["environment"]
    all_runs = [run for part in parts for run in part["runs"]]
    runs = [run for run in all_runs if not run.get("memory_only")]
    peaks: dict[tuple[str, str], float] = {}
    for run in all_runs:
        key = ("", str(run["tool"]).replace(" diff", "").split(",")[0])
        if not run.get("failed"):
            peaks[key] = max(peaks.get(key, 0.0), float(run["peak_mb_max"]))
    order = ["nginx", "app", "loghub", "highcard", "highcard@10MB"]
    datasets = [name for name in order if any(r["dataset"] == name for r in runs)]
    raw = ", ".join(f"`{path.relative_to(ROOT).as_posix()}`" for path in paths)
    out = [
        "# Benchmark results",
        "",
        f"Protocol: [`PROTOCOL.md`](PROTOCOL.md). Raw data: {raw}.",
        "",
        f"Machine: {env['os']}, {env['cores_physical']} physical / {env['cores_logical']} logical cores, "
        f"{env['ram_gb']} GB RAM, Python {env['python']}.",
        "",
        "Tools: " + "; ".join(f"{name}: {value}" for name, value in env["tools"].items()) + ".",
        "",
        "Wall time of the median of the repeats in seconds, with throughput in MB/s in brackets. Best per column in bold.",
        "",
    ]
    titles = {
        "analyze-bare": "Analyze, no masking",
        "analyze-masked": "Analyze, with masking",
        "diff": "Diff of two 100 MB runs (throughput counts both files)",
    }
    for scenario, title in titles.items():
        rows = table(runs, scenario, datasets, peaks)
        if rows:
            out += [f"## {title}", "", *rows, ""]
    notes = ROOT / "bench" / "NOTES.md"
    if notes.exists():
        out += ["", notes.read_text(encoding="utf-8").rstrip(), ""]
    (ROOT / "bench" / "RESULTS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote bench/RESULTS.md")


if __name__ == "__main__":
    main()
