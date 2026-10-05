"""Run Drain3 over a file the way the benchmark runner needs it (parameters aligned with logfold defaults)."""

from __future__ import annotations

import argparse
import sys
import time

from drain3 import TemplateMiner
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

from logfold.config import DEFAULT_MASKS


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--masks", choices=("none", "default"), default="none")
    args = parser.parse_args()
    config = TemplateMinerConfig()
    config.drain_depth = 4
    config.drain_sim_th = 0.4
    config.drain_max_children = 100
    config.profiling_enabled = False
    if args.masks == "default":
        config.masking_instructions = [
            MaskingInstruction(rule.pattern, rule.token.strip("<>")) for rule in DEFAULT_MASKS
        ]
    miner = TemplateMiner(config=config)
    started = time.perf_counter()
    lines = 0
    with open(args.path, encoding="utf-8", errors="replace") as stream:
        for line in stream:
            miner.add_log_message(line.rstrip("\n"))
            lines += 1
    elapsed = time.perf_counter() - started
    sys.stdout.write(f"lines={lines} templates={len(miner.drain.clusters)} seconds={elapsed:.2f}\n")


if __name__ == "__main__":
    main()
