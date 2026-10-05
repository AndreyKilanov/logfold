"""Render the files in ``bench/results`` as Markdown tables (``bench/RESULTS.md``).

Usage::

    python bench/tools/report.py [results directory]
"""

from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load_results(folder: Path) -> tuple[dict[str, object], list[dict[str, object]]]:
    """Read ``environment.json`` and every scenario file of ``folder``."""
    if not (folder / "environment.json").exists():
        raise SystemExit(f"no results in {folder}; run bench/tools/run.py first")
    environment = json.loads((folder / "environment.json").read_text(encoding="utf-8"))
    runs: list[dict[str, object]] = []
    for scenario in ("analyze-bare", "analyze-masked", "diff"):
        path = folder / f"{scenario}.json"
        if path.exists():
            runs += json.loads(path.read_text(encoding="utf-8"))["runs"]
    return environment, runs


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


DIFF_SCALE_COLUMNS = (
    ("analyze_s", "analyze"),
    ("analyze_engine_s", "engine part"),
    ("diff_exact_s", "diff exact"),
    ("diff_token_subset_s", "diff token_subset"),
    ("diff_jaccard_s", "diff jaccard"),
)
DIFF_SCALE_STAGES = {
    "before": "Before: the matchers compared every pair of templates",
    "indexed": "Candidates found with an index, in Python",
    "native": "The matchers in Rust",
    "columns": "Columnar result and the comparison in Rust (current)",
}
PROJECT_TO = (54_000, 100_000)


def exponent(rows: list[dict[str, object]], key: str) -> float | None:
    """Fit ``t ~ n^k`` between the first and the last size that has a time for ``key``."""
    timed = [(float(r["templates"]), float(r[key])) for r in rows if r.get(key)]  # type: ignore[arg-type]
    if len(timed) < 2 or timed[0][1] <= 0:
        return None
    (n1, t1), (n2, t2) = timed[0], timed[-1]
    return math.log(t2 / t1) / math.log(n2 / n1)


def project(rows: list[dict[str, object]], key: str, templates: int) -> float | None:
    """Extrapolate the time of ``key`` to ``templates`` templates with the fitted exponent."""
    k = exponent(rows, key)
    timed = [r for r in rows if r.get(key)]
    if k is None or not timed:
        return None
    last = timed[-1]
    return float(last[key]) * (templates / float(last["templates"])) ** k  # type: ignore[arg-type]


def _cell(value: object) -> str:
    return "skipped" if value is None else f"{float(value):,.2f}"  # type: ignore[arg-type]


def diff_scale_table(rows: list[dict[str, object]]) -> list[str]:
    """Render the rows of one stage: the times in seconds, the growth exponent and the projections."""
    keys = [(key, title) for key, title in DIFF_SCALE_COLUMNS if any(key in row for row in rows)]
    out = ["| lines | templates | " + " | ".join(title for _, title in keys) + " |"]
    out.append("|---:|---:|" + "---:|" * len(keys))
    for row in rows:
        out.append(
            f"| {int(row['lines']):,} | {int(row['templates']):,} | "
            + " | ".join(_cell(row.get(k)) for k, _ in keys)
            + " |"
        )  # type: ignore[call-overload]
    exponents = ["growth exponent"] + [f"{k:.2f}" if (k := exponent(rows, key)) is not None else "" for key, _ in keys]
    out.append("| " + " | ".join(["", *exponents]) + " |")
    for n in PROJECT_TO:
        cells = [_cell(project(rows, key, n)) if exponent(rows, key) is not None else "" for key, _ in keys]
        out.append(f"| | projected at {n:,} templates | " + " | ".join(cells) + " |")
    return out


def diff_scale_section(data: dict[str, object]) -> list[str]:
    """Render ``results/diff-scale.json`` (stages of `bench/tools/diff_scale.py`) as a section."""
    stages = data["stages"]  # type: ignore[index]
    out = [
        "## `diff` and result building: growth with the number of templates",
        "",
        "Measured by `tools/diff_scale.py`: three to five small sizes (4.6 to 73 thousand templates per run), best of three "
        "repeats for the fast measurements, one thread, native engine. `diff` compares two saved results; `analyze` is the "
        "whole call, the engine part is the time inside the engine. The growth exponent `k` of `t ~ n^k` is fitted between "
        "the first and the last size, the last two rows extrapolate with it.",
        "",
    ]
    for stage, title in DIFF_SCALE_STAGES.items():
        if stage in stages:  # type: ignore[operator]
            out += [f"### {title}", "", *diff_scale_table(stages[stage]["rows"]), ""]  # type: ignore[index]
    out += [
        "What is left is Python object construction: a `DiffEntry` costs about 5 microseconds (these logs share few "
        "templates, so almost every template is reported) and a `Template` in `analyze` about 4.",
        "",
    ]
    return out


def main() -> None:
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "bench" / "results"
    env, all_runs = load_results(folder)
    runs = [run for run in all_runs if not run.get("memory_only")]
    peaks: dict[tuple[str, str], float] = {}
    for run in all_runs:
        key = ("", str(run["tool"]).replace(" diff", "").split(",")[0])
        if not run.get("failed"):
            peaks[key] = max(peaks.get(key, 0.0), float(run["peak_mb_max"]))  # type: ignore[arg-type]
    order = ["nginx", "app", "loghub", "highcard", "highcard@10MB"]
    present = {str(r["dataset"]) for r in runs}
    datasets = [name for name in order if name in present] + sorted(present - set(order))
    out = [
        "# Benchmark results",
        "",
        "Protocol: [`PROTOCOL.md`](PROTOCOL.md). Raw data: [`results/`](results).",
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
    scale = folder / "diff-scale.json"
    if scale.exists():
        out += diff_scale_section(json.loads(scale.read_text(encoding="utf-8")))
    notes = ROOT / "bench" / "docs" / "NOTES.md"
    if notes.exists():
        out += ["", notes.read_text(encoding="utf-8").rstrip(), ""]
    (ROOT / "bench" / "RESULTS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote bench/RESULTS.md")


if __name__ == "__main__":
    main()
