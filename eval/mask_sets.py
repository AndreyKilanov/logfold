"""What the built-in mask sets do to ordinary logs: grouping accuracy and false positives on Loghub-2k.

For every dataset the script mines the message column twice, with the default masks and with the sets added in front of
them, and reports the grouping accuracy of both (see ``quality.py``) and how many messages the sets changed. Loghub
holds no real secrets, so every changed message is a false positive of a rule or a value it happened to catch (a card
number in a log would be a find, not a false alarm); ``--show`` prints a sample of them.

Usage::

    python eval/mask_sets.py --sets all --out eval/results/mask_sets.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quality

from logfold.config import DEFAULT_MASKS
from logfold.ext import resolve_masks
from logfold.ext.masks import Masker


def accuracy(messages: list[str], events: list[str], rules: tuple, **options: object) -> tuple[float, int]:
    """Grouping accuracy and number of templates when mining and assigning with ``rules``."""
    quality.MASKER = Masker(rules)
    templates = quality.logfold_templates(messages, strategy="sequential", masks=list(rules), **options)
    return quality.grouping_accuracy(quality.assign(messages, templates), events), len(templates)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("eval/data"))
    parser.add_argument("--out", type=Path, default=Path("eval/results/mask_sets.json"))
    parser.add_argument("--sets", nargs="+", default=["all"])
    parser.add_argument("--show", type=int, default=0, help="print this many changed messages per dataset")
    args = parser.parse_args()
    with_sets = resolve_masks(args.sets)
    base, extra = Masker(DEFAULT_MASKS), Masker(with_sets)
    table: dict[str, dict[str, float]] = {}
    for name in quality.DATASETS:
        messages, events = quality.load(name, args.data)
        changed = [m for m in messages if base.mask(m) != extra.mask(m)]
        plain_ga, plain_templates = accuracy(messages, events, DEFAULT_MASKS)
        sets_ga, sets_templates = accuracy(messages, events, with_sets)
        table[name] = {
            "messages": len(messages),
            "changed": len(changed),
            "ga_default": plain_ga,
            "ga_sets": sets_ga,
            "templates_default": plain_templates,
            "templates_sets": sets_templates,
        }
        print(f"{name:12} changed {len(changed):4}/{len(messages)}  GA {plain_ga:.4f} -> {sets_ga:.4f}", flush=True)
        for message in changed[: args.show]:
            print(f"    {message[:150]!r}\n      -> {extra.mask(message)[:150]!r}")
    average = {key: sum(row[key] for row in table.values()) / len(table) for key in ("ga_default", "ga_sets")}
    print(f"average GA {average['ga_default']:.4f} -> {average['ga_sets']:.4f}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"sets": args.sets, "per_dataset": table, "average": average}, indent=2)
    args.out.write_text(payload + "\n", encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
