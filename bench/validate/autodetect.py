"""The format auto-detection (``-f auto``) against a matrix of logs.

A wrong guess is the worst failure of detection: the log is parsed quietly with the wrong format. For every file (see
``autodetect_corpus.py``) and every damaged form of it this script asks the detector and sorts the answer:

* **correct**: the format that is meant for the file (``nginx`` and ``apache`` are the same pattern);
* **compatible**: another format that reads the file into the same records, lines not parsed and levels;
* **refused**: ``plain`` or the explicit "cannot detect" error (the user names the format; never a quiet mistake);
* **wrong**: another format that reads the file differently, or any format for a file that no built-in format reads.

It also sweeps ``CONFIDENCE_THRESHOLD``: the same files, decided at other thresholds. Exit code 1 when anything is wrong.

Usage::

    LOGFOLD_KEEP_LOGS=bench/data/formats/real python bench/validate/formats.py <program>   # once, needs docker
    python bench/validate/autodetect.py [--only SOURCE] [--json FILE]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path

from autodetect_corpus import VARIANTS, Entry, external_logs, generated_logs, loghub_logs, real_logs

import logfold
from logfold.formats.auto import CONFIDENCE_THRESHOLD, candidates, read_sample
from logfold.formats.auto import _score as score_format

THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 1.0)
OUTCOMES = ("correct", "compatible", "refused", "wrong")
SAME_PATTERN = {"nginx": "apache", "apache": "nginx"}
GENERIC_READS = {("haproxy", "syslog")}
"""Pairs (the format of the file, the format picked) that read a different record but lose no line and split none: HAProxy
writes through syslog, so a log of it is a syslog log, and ``syslog`` keeps the whole line as the message."""


@dataclass
class Case:
    """One file in one damaged form, and what the detector said."""

    source: str
    name: str
    variant: str
    truth: str | None
    picked: str | None
    confidence: float
    outcome: str
    scores: dict[str, float]


def family(spec: str | None) -> str | None:
    """Return the name of a format without its pattern (``log4j:%d ...`` is ``log4j``)."""
    return spec.split(":", 1)[0] if spec else None


def parse_key(path: Path, spec: str) -> tuple[int, int, tuple[tuple[str, int], ...]]:
    """Read ``path`` with ``spec`` and return what a parse is judged by: records, lines not parsed, records per level."""
    result = logfold.analyze(path, format=spec)
    return result.run.records, result.run.unparsed, tuple(sorted(result.levels.items()))


def decide(scores: dict[str, float], threshold: float) -> str | None:
    """Return the format the detector picks at ``threshold`` (the first best in detection order) or ``None``."""
    best = max(scores, key=lambda name: scores[name])
    return best if scores[best] >= threshold else None


def judge(entry: Entry, path: Path, picked: str | None, parsed: dict[tuple[Path, str], object]) -> str:
    """Sort an answer into ``correct``, ``compatible``, ``refused`` or ``wrong``."""
    if picked is None:
        return "refused"
    if entry.truth is None:
        return "wrong"
    truth = family(entry.truth)
    if picked == truth or SAME_PATTERN.get(picked) == truth:
        return "correct"
    if (truth, picked) in GENERIC_READS:
        return "compatible"
    for spec in (picked, entry.truth):
        if (path, spec) not in parsed:
            parsed[path, spec] = parse_key(path, spec)
    same = parsed[path, picked] == parsed[path, entry.truth]
    return "compatible" if same else "wrong"


def run_entry(entry: Entry, scratch: Path) -> list[tuple[Case, list[str]]]:
    """Return the cases of one file: one per damaged form, and the outcome at each threshold of the sweep."""
    cases = []
    original = entry.path.read_bytes()
    for variant, damage in VARIANTS.items():
        path = scratch / f"{variant}.log"
        path.write_bytes(damage(original))
        parsed: dict[tuple[Path, str], object] = {}
        lines = read_sample(str(path))
        scores = {name: score_format(spec, lines)[0] for name, spec in candidates().items()}
        picked = decide(scores, CONFIDENCE_THRESHOLD)
        outcome = judge(entry, path, picked, parsed)
        sweep = [judge(entry, path, decide(scores, threshold), parsed) for threshold in THRESHOLDS]
        confidence = scores[picked] if picked else max(scores.values())
        cases.append((Case(entry.source, entry.name, variant, entry.truth, picked, confidence, outcome, scores), sweep))
    return cases


def table(rows: dict[str, Counter[str]], title: str) -> None:
    """Print one markdown table of outcomes per row key."""
    print(f"\n| {title} | cases | {' | '.join(OUTCOMES)} |\n|---|---:|{'---:|' * len(OUTCOMES)}")
    for key in sorted(rows, key=str):
        counts = rows[key]
        print(f"| {key} | {sum(counts.values())} | {' | '.join(str(counts[name]) for name in OUTCOMES)} |")


def main() -> None:
    """Run the matrix and print the tables."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="run only the sources whose name contains this text")
    parser.add_argument("--json", type=Path, help="write every case to this file")
    args = parser.parse_args()
    if not logfold._bridge.is_available():
        sys.exit("the native extension is not built: run `maturin develop --release`")
    cases: list[Case] = []
    sweeps: dict[float, Counter[str]] = {threshold: Counter() for threshold in THRESHOLDS}
    with tempfile.TemporaryDirectory() as folder:
        scratch = Path(folder)
        work = scratch / "work"
        work.mkdir()
        entries = real_logs() + external_logs() + loghub_logs(scratch) + generated_logs(scratch)
        for entry in entries:
            if args.only and args.only not in entry.source:
                continue
            for case, sweep in run_entry(entry, work):
                cases.append(case)
                for threshold, outcome in zip(THRESHOLDS, sweep, strict=True):
                    sweeps[threshold][outcome] += 1
    by_truth: dict[str, Counter[str]] = defaultdict(Counter)
    by_source: dict[str, Counter[str]] = defaultdict(Counter)
    by_variant: dict[str, Counter[str]] = defaultdict(Counter)
    for case in cases:
        by_truth[family(case.truth) or "(none)"][case.outcome] += 1
        by_source[case.source][case.outcome] += 1
        by_variant[case.variant][case.outcome] += 1
    print(f"{len(cases) // len(VARIANTS)} files, {len(cases)} cases, threshold {CONFIDENCE_THRESHOLD}")
    table(by_source, "source")
    table(by_truth, "format of the file")
    table(by_variant, "damaged form")
    table({f"{threshold}": counts for threshold, counts in sweeps.items()}, "threshold")
    wrong = [case for case in cases if case.outcome == "wrong"]
    for case in wrong:
        best = sorted(case.scores.items(), key=lambda item: -item[1])[:2]
        print(
            f"WRONG {case.source}/{case.name} [{case.variant}]: truth {case.truth}, picked {case.picked}, scores {best}"
        )
    refused = [case.confidence for case in cases if case.outcome == "refused" and case.truth]
    right = [case.confidence for case in cases if case.outcome in ("correct", "compatible")]
    print(
        f"\nlowest confidence of a right answer: {min(right, default=0):.2f}; "
        f"highest best score of a refused file that has a format: {max(refused, default=0):.2f}"
    )
    if args.json:
        args.json.write_text(json.dumps([asdict(case) for case in cases], indent=1), encoding="utf-8", newline="\n")
    sys.exit(1 if wrong else 0)


if __name__ == "__main__":
    main()
