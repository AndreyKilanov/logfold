"""Which `diff` matcher to use by default: measured on before/after pairs cut from real logs.

For every log the script builds three kinds of pairs from windows of its first lines and runs ``diff`` with each matcher:

* ``stationary``: the window is split into blocks of ``--block`` lines that go alternately to *before* and *after*. Both
  sides come from the same distribution, so every reported template is noise. The number of reported templates is the
  false-alarm count (lower is better).
* ``adjacent``: two consecutive windows, so the log drifts a little. There is no ground truth; the counts show how much
  each matcher hides and a sample of its pairs lets a person judge them.
* ``reworded``: a stationary pair in which, in *after*, one word ``W`` is replaced on every line that has it, like a
  release that rewords a message. Mode ``swap`` replaces it by ``W_v2`` (same length), mode ``extend`` by the two
  tokens ``W_v2 extra`` (longer), mode ``novel`` rewrites all words of those lines. The truth is known: every template of *before* that contains ``W`` must be paired
  with its reworded twin. A pair joins a template to its *twin* when the template of *before*, with ``W`` reworded the same way,
  agrees with the template of *after* at every position (equal tokens or a wildcard on either side). The miner can
  absorb a reworded template into a more general one, so only the *reachable* templates (those that have such a twin
  among the templates of *after*) count for recall. Mode ``novel`` is the opposite test: every plain word of the lines
  with ``W`` is rewritten, which is a different message, so a twin pair there is a false merge.

Every pair is run twice: ``live`` (``diff`` of the two files: one shared tree and a recount) and ``saved``
(each file analyzed on its own and the two results compared, like ``logfold diff before.json after.json``).

Raw results go to ``bench/results/diff-matchers.json``; the discussion is in ``bench/docs/DIFF_MATCHERS.md``.

Usage::

    python bench/tools/diff_matchers.py --window 3000000
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

import logfold
from logfold.comparison.matchers import WILDCARD
from logfold.ext import registry

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "bench" / "data" / "loghub2"
OUT = ROOT / "bench" / "results" / "diff-matchers.json"
LOGS = ("hdfs", "bgl", "spark", "thunderbird")
MATCHERS = ("exact", "token_subset", "jaccard", "jaccard-idf", "overlap")
SOURCES = ("live", "saved")
WORD = re.compile(r"^[A-Za-z]{4,}$")
MODES = ("swap", "extend", "novel")


def read_lines(path: Path, count: int) -> list[str]:
    """Return the first ``count`` lines of a log, without line terminators."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            lines.append(line.rstrip("\n"))
            if len(lines) == count:
                break
    return lines


def split_blocks(lines: list[str], block: int) -> tuple[list[str], list[str]]:
    """Deal blocks of ``block`` lines alternately to two lists, keeping the order inside each list."""
    first: list[str] = []
    second: list[str] = []
    for start in range(0, len(lines), block):
        (first if start // block % 2 == 0 else second).extend(lines[start : start + block])
    return first, second


def pick_words(lines: list[str], count: int) -> list[str]:
    """Pick ``count`` plain words that occur on 0.5 to 20 percent of the lines, spread over that range."""
    seen: Counter[str] = Counter()
    for line in lines:
        seen.update({token for token in line.split(" ") if WORD.match(token)})
    low, high = len(lines) * 0.005, len(lines) * 0.2
    candidates = sorted((word for word, n in seen.items() if low <= n <= high), key=lambda w: (-seen[w], w))
    if not candidates:
        return []
    step = max(len(candidates) // count, 1)
    return candidates[::step][:count]


def expand(tokens: list[str], word: str, mode: str) -> list[str]:
    """Apply the rewording ``mode`` to a token list that contains ``word``; other lists are returned unchanged.

    ``swap`` replaces ``word`` by ``word_v2``, ``extend`` by the two tokens ``word_v2 extra``, ``novel`` rewrites every
    plain word of the list into an unrelated one, so the numbers, addresses and punctuation stay and only the message
    is new (the hardest case for a matcher: it must not pair the result with the original).
    """
    if word not in tokens:
        return tokens
    out: list[str] = []
    for token in tokens:
        if mode == "novel" and token.isalpha():
            out.append(token[::-1] + "_nx")
        elif token == word and mode == "swap":
            out.append(token + "_v2")
        elif token == word and mode == "extend":
            out.extend((token + "_v2", "extra"))
        else:
            out.append(token)
    return out


def reword(lines: list[str], word: str, mode: str) -> list[str]:
    """Reword ``word`` on every line."""
    return [" ".join(expand(line.split(" "), word, mode)) for line in lines]


def write(path: Path, lines: list[str]) -> Path:
    """Write ``lines`` to ``path`` and return it."""
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class Pair:
    """Two plain-text files compared in both ways, with the analyses of the ``saved`` way made once."""

    def __init__(self, before: Path, after: Path) -> None:
        self.before = before
        self.after = after
        self._saved: tuple[logfold.AnalysisResult, logfold.AnalysisResult] | None = None

    def diff(self, matcher: str, source: str, strategy: str = "auto") -> tuple[logfold.DiffResult, float]:
        """Run ``diff`` with ``matcher`` and return the result and its wall time in seconds.

        ``source`` is ``live`` (both files mined with one shared tree and recounted, the time includes mining) or
        ``saved`` (each file analyzed on its own, as ``diff before.json after.json`` does; only the comparison of the
        two saved results is timed). ``strategy`` is the execution strategy of the live way.
        """
        if source == "saved":
            if self._saved is None:
                self._saved = tuple(  # type: ignore[assignment]
                    logfold.analyze(path, format="plain", examples="none") for path in (self.before, self.after)
                )
            assert self._saved is not None
            start = time.perf_counter()
            result = logfold.diff(*self._saved, matcher=matcher, significance=1.0)
        else:
            start = time.perf_counter()
            result = logfold.diff(
                self.before,
                self.after,
                format="plain",
                matcher=matcher,
                examples="none",
                strategy=strategy,
                significance=1.0,
            )
        return result, time.perf_counter() - start


def timing(pair: Pair, source: str, repeat: int, strategy: str = "auto") -> dict[str, Any]:
    """Wall time of ``diff`` per matcher: the median and the extremes of ``repeat`` runs."""
    out: dict[str, Any] = {}
    for matcher in MATCHERS:
        seconds = sorted(pair.diff(matcher, source, strategy)[1] for _ in range(repeat))
        out[matcher] = {"median_s": seconds[len(seconds) // 2], "min_s": seconds[0], "max_s": seconds[-1]}
    return out


def counts(result: logfold.DiffResult) -> dict[str, int]:
    """Number of entries per class."""
    return {
        "new": len(result.new_templates),
        "disappeared": len(result.disappeared),
        "changed": len(result.changed),
        "alarms": len(result.new_templates) + len(result.disappeared) + len(result.changed),
    }


def compatible(general: list[str], specific: list[str]) -> bool:
    """Whether two token lists agree at every position (equal tokens or a wildcard on either side)."""
    return len(general) == len(specific) and all(
        a in (b, WILDCARD) or b == WILDCARD for a, b in zip(general, specific, strict=True)
    )


def evaluate_pairs(before_only: list[str], after_only: list[str], matcher: str, word: str, mode: str) -> dict[str, Any]:
    """Score the pairs of one matcher against the known rewording of ``word``.

    A pair is a *twin* pair when it joins a template that contains ``word`` with its reworded twin, *misplaced* when it
    joins such a template with another one (*foreign* when that other template is not a reworded one either: a real
    false merge; the rest are mix-ups between reworded siblings), and *other* when it does not involve the reworded templates at all (the
    noise that the stationary pair also has).
    """
    pairs = registry.get_matcher(matcher).match(before_only, after_only)
    expected = {i for i, text in enumerate(before_only) if word in text.split(" ")}
    marker = expand([word], word, mode)[0]
    twin = misplaced = foreign = 0
    for i, j in pairs:
        if i not in expected:
            continue
        if compatible(expand(before_only[i].split(" "), word, mode), after_only[j].split(" ")):
            twin += 1
        else:
            misplaced += 1
            foreign += marker not in after_only[j].split(" ")
    after_tokens = [text.split(" ") for text in after_only]
    reachable = sum(
        any(compatible(expand(before_only[i].split(" "), word, mode), other) for other in after_tokens)
        for i in expected
    )
    return {
        "expected": len(expected),
        "reachable": reachable,
        "pairs": len(pairs),
        "twin": twin,
        "misplaced": misplaced,
        "foreign": foreign,
        "other": len(pairs) - twin - misplaced,
        "twin_share": twin / reachable if reachable else None,
    }


def pair_kind(before: str, after: str) -> str:
    """Classify a pair of templates: ``generalizing``, ``same length`` (literals differ) or ``other length``."""
    left, right = before.split(" "), after.split(" ")
    if len(left) != len(right):
        return "other length"
    return "generalizing" if compatible(left, right) else "same length"


def pair_stats(before_only: list[str], after_only: list[str], matcher: str, limit: int) -> dict[str, Any]:
    """Count the pairs of ``matcher`` by kind and return a sample, evenly spread over the pairs."""
    pairs = registry.get_matcher(matcher).match(before_only, after_only)
    kinds = Counter(pair_kind(before_only[i], after_only[j]) for i, j in pairs)
    step = max(len(pairs) // limit, 1)
    sample = [
        [pair_kind(before_only[i], after_only[j]), before_only[i], after_only[j]] for i, j in pairs[::step][:limit]
    ]
    return {"pairs": len(pairs), "kinds": dict(kinds), "sample": sample}


def stationary_and_adjacent(
    name: str, lines: list[str], window: int, block: int, repeat: int, tmp: Path
) -> dict[str, Any]:
    """Run the pairs that have no ground truth; the adjacent pair is also timed."""
    first, second = split_blocks(lines[: 2 * window], block)
    pairs = {
        "stationary": Pair(write(tmp / f"{name}-s-a.log", first), write(tmp / f"{name}-s-b.log", second)),
        "adjacent": Pair(
            write(tmp / f"{name}-n-a.log", lines[:window]), write(tmp / f"{name}-n-b.log", lines[window : 2 * window])
        ),
    }
    out: dict[str, Any] = {}
    for scenario, pair in pairs.items():
        for source in SOURCES:
            results = {m: pair.diff(m, source)[0] for m in MATCHERS}
            exact = results["exact"]
            before_only = [e.text for e in exact.disappeared]
            after_only = [e.text for e in exact.new_templates]
            out[f"{scenario}/{source}"] = {
                "records": [exact.before.records, exact.after.records],
                "matchers": {m: counts(r) for m, r in results.items()},
                "pairs": {m: pair_stats(before_only, after_only, m, 20) for m in MATCHERS[1:]},
            }
            if scenario == "adjacent":
                out[f"{scenario}/{source}"]["timing"] = timing(pair, source, repeat)
                if source == "live":
                    out[f"{scenario}/{source}"]["timing_one_thread"] = timing(pair, source, repeat, "sequential")
    return out


def reworded(name: str, lines: list[str], window: int, block: int, words: int, tmp: Path) -> list[dict[str, Any]]:
    """Run the pair with a known rewording once per picked word."""
    first, second = split_blocks(lines[: 2 * window], block)
    before = write(tmp / f"{name}-r-a.log", first)
    results: list[dict[str, Any]] = []
    for word in pick_words(first, words):
        for mode in MODES:
            pair = Pair(before, write(tmp / f"{name}-r-b.log", reword(second, word, mode)))
            for source in SOURCES:
                exact = pair.diff("exact", source)[0]
                before_only = [e.text for e in exact.disappeared]
                after_only = [e.text for e in exact.new_templates]
                results.append(
                    {
                        "word": word,
                        "mode": mode,
                        "source": source,
                        "matchers": {m: evaluate_pairs(before_only, after_only, m, word, mode) for m in MATCHERS[1:]},
                        "one_sided": [len(before_only), len(after_only)],
                    }
                )
    return results


def main() -> None:
    """Run all scenarios on all logs and store the results."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--window", type=int, default=3_000_000, help="lines in one side of a pair (fewer if the log is shorter)"
    )
    parser.add_argument("--block", type=int, default=1000, help="block size of the stationary split")
    parser.add_argument("--words", type=int, default=3, help="reworded words per log")
    parser.add_argument("--repeat", type=int, default=3, help="repeats of the timed runs")
    parser.add_argument("--logs", nargs="+", default=list(LOGS), choices=LOGS)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()
    report: dict[str, Any] = {
        "logfold": logfold.__version__,
        "python": platform.python_version(),
        "max_window": args.window,
        "block": args.block,
        "repeat": args.repeat,
        "logs": {},
    }
    with tempfile.TemporaryDirectory() as directory:
        tmp = Path(directory)
        for name in args.logs:
            lines = read_lines(DATA / f"{name}.txt", 2 * args.window)
            window = min(args.window, len(lines) // 2)
            print(f"{name}: {len(lines)} lines read, {window} per side", flush=True)
            entry = {"window": window}
            entry.update(stationary_and_adjacent(name, lines, window, args.block, args.repeat, tmp))
            entry["reworded"] = reworded(name, lines, window, args.block, args.words, tmp)
            report["logs"][name] = entry
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
