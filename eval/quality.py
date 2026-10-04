"""Template quality on Loghub-2k: grouping accuracy of logfold against Drain3.

Every system produces a set of templates for the message column of a Loghub-2k sample. Lines are then assigned to those
templates with one common procedure, and grouping accuracy (GA, as in the Loghub benchmark) is computed against the
ground-truth event ids: a predicted group counts as correct only if it holds exactly the lines of one true event.

Usage::

    python eval/quality.py --out eval/results/quality.json
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tempfile
import urllib.request
from collections import defaultdict
from pathlib import Path

import logfold
from logfold.config import DEFAULT_MASKS
from logfold.ext.masks import Masker

DATASETS = (
    "Android",
    "Apache",
    "BGL",
    "Hadoop",
    "HDFS",
    "HealthApp",
    "HPC",
    "Linux",
    "Mac",
    "OpenSSH",
    "OpenStack",
    "Proxifier",
    "Spark",
    "Thunderbird",
    "Windows",
    "Zookeeper",
)
STRUCTURED = "https://raw.githubusercontent.com/logpai/loghub/master/{name}/{name}_2k.log_structured.csv"
WILDCARD = "<*>"
THRESHOLD_MICRO = 400_000


def load(name: str, cache: Path) -> tuple[list[str], list[str]]:
    """Return ``(messages, event_ids)`` of a Loghub-2k sample."""
    path = cache / f"{name}_2k.log_structured.csv"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(STRUCTURED.format(name=name), path)
    messages, events = [], []
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            messages.append(row["Content"])
            events.append(row["EventId"])
    return messages, events


MASKER = Masker(DEFAULT_MASKS)


def tokenize(message: str) -> list[str]:
    return MASKER.mask(message).split()


def assign(messages: list[str], templates: list[str]) -> list[str]:
    """Assign each message to its best-matching template (full scan, Drain scoring); unmatched lines stay alone."""
    by_length: dict[int, list[tuple[int, list[str]]]] = defaultdict(list)
    for index, template in enumerate(templates):
        tokens = template.split()
        by_length[len(tokens)].append((index, tokens))
    labels = []
    for line_number, message in enumerate(messages):
        tokens = tokenize(message)
        best: tuple[int, int, int] | None = None
        for index, template in by_length.get(len(tokens), []):
            exact = sum(1 for t, m in zip(template, tokens, strict=True) if t == m and t != WILDCARD)
            params = sum(1 for t in template if t == WILDCARD)
            candidate = (exact + params, params, -index)
            if best is None or candidate > best:
                best = candidate
        if best is not None and best[0] * 1_000_000 >= THRESHOLD_MICRO * len(tokens):
            labels.append(f"t{-best[2]}")
        else:
            labels.append(f"alone{line_number}")
    return labels


def grouping_accuracy(predicted: list[str], truth: list[str]) -> float:
    pred_groups: dict[str, set[int]] = defaultdict(set)
    true_groups: dict[str, set[int]] = defaultdict(set)
    for index, (p, t) in enumerate(zip(predicted, truth, strict=True)):
        pred_groups[p].add(index)
        true_groups[t].add(index)
    true_sets = {frozenset(group) for group in true_groups.values()}
    correct = sum(len(group) for group in pred_groups.values() if frozenset(group) in true_sets)
    return correct / len(predicted)


def logfold_templates(messages: list[str], **options: object) -> list[str]:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "messages.log"
        path.write_text("\n".join(m.replace("\n", " ") for m in messages) + "\n", encoding="utf-8")
        result = logfold.analyze(str(path), format="plain", examples="none", **options)  # type: ignore[arg-type]
    return [t.text for t in result.templates]


def drain3_templates(messages: list[str]) -> list[str]:
    from drain3 import TemplateMiner
    from drain3.masking import MaskingInstruction
    from drain3.template_miner_config import TemplateMinerConfig

    config = TemplateMinerConfig()
    config.drain_depth = 4
    config.drain_sim_th = 0.4
    config.drain_max_children = 100
    config.profiling_enabled = False
    config.masking_instructions = [MaskingInstruction(rule.pattern, rule.token.strip("<>")) for rule in DEFAULT_MASKS]
    miner = TemplateMiner(config=config)
    for message in messages:
        miner.add_log_message(message)
    return [cluster.get_template() for cluster in miner.drain.clusters]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("eval/data"))
    parser.add_argument("--out", type=Path, default=Path("eval/results/quality.json"))
    parser.add_argument("--chunk-bytes", type=int, default=24_000, help="chunk size that forces tree merges")
    args = parser.parse_args()
    systems = {
        "drain3": lambda m: drain3_templates(m),
        "logfold-sequential": lambda m: logfold_templates(m, strategy="sequential"),
        "logfold-chunked": lambda m: logfold_templates(m, strategy="chunked", threads=4, chunk_bytes=args.chunk_bytes),
    }
    table: dict[str, dict[str, float]] = {}
    for name in DATASETS:
        messages, events = load(name, args.data)
        table[name] = {}
        for system, build in systems.items():
            templates = build(messages)
            table[name][system] = grouping_accuracy(assign(messages, templates), events)
            table[name][f"{system}:templates"] = len(templates)
        print(name, {k: round(v, 3) for k, v in table[name].items()}, file=sys.stderr, flush=True)
    averages = {system: sum(row[system] for row in table.values()) / len(table) for system in systems}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"per_dataset": table, "average": averages}, indent=2), encoding="utf-8")
    print(json.dumps(averages, indent=2))


if __name__ == "__main__":
    main()
