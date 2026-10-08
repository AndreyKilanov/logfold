"""Golden outputs of the pipeline reports: the cases, their fingerprints and the command that regenerates the file.

``tests/fixtures/golden/reports.json`` holds the SHA-256 of the text that every report wrote for every case below. The
values were taken from the pure-Python reporters, which the Rust renderers replaced (``docs/ALGORITHM.md`` section 12).
Change the file only together with a deliberate change of that section: ``python tests/golden_reports.py`` rewrites it
from the current reporters.
"""

from __future__ import annotations

import hashlib
import json
import random
import tempfile
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import logfold
from corpora import hostile_pair
from logfold.ext import get_reporter
from logfold.model import AnalysisResult, DiffEntry, DiffResult, RunSummary, Template

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "reports.json"
REPORTS = ("github-summary", "junit", "chat-message", "prometheus")
LIMITS = {"github-summary": "max_bytes", "chat-message": "max_chars"}
PIECES = [
    "a", "word", "<NUM>", "<*>", "x" * 90, "y" * 450, "`", "``", "|", '"', chr(92), "&", "<", ">", "]]>",
    "<!here>", "<@U123>", "<#C1>", "@channel", "@HERE", "@all", "@everyone", "@channels", "@all_", "@all.", "@ALL",
    "\x1b[31m", "\x00", "\x07", "\x1f", "\x7f", "\x85", "\t", "\n", "\r", " ", "  ", chr(0xA0), chr(0x2028),
    chr(0x3000), chr(0x200B), chr(0xFFFE), chr(0xFFFF), chr(0x301), "é", "Ж", "日本語", "\U0001f642", "\U00010000",
]  # fmt: skip
LEVELS = [None, None, "TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL", "ERRORISH", "<b>x</b>"]
IDS = ["0123456789abcdef", "ffffffffffffffff", "ab" + chr(92) + '"c', ""]
RANDOM_CASES = 150
Case = tuple[str, str, AnalysisResult | DiffResult, dict[str, int]]


def _bases() -> tuple[AnalysisResult, DiffResult]:
    with tempfile.TemporaryDirectory() as folder:
        before, after = hostile_pair(Path(folder))
        diff = logfold.diff(str(before), str(after), format="app", engine="native", strategy="sequential")
        analysis = logfold.analyze(str(after), format="app", engine="native", strategy="sequential")
    analysis = replace(analysis, run=replace(analysis.run, name="hostile_after.log"))
    diff = replace(
        diff,
        before=replace(diff.before, name="hostile_before.log"),
        after=replace(diff.after, name="hostile_after.log"),
    )
    return analysis, diff


def _text(rng: random.Random) -> str:
    pieces = [rng.choice(PIECES) for _ in range(rng.randrange(0, 10))]
    return ("" if rng.random() < 0.5 else " ").join(pieces)


def _name(rng: random.Random) -> str:
    return rng.choice(
        [_text(rng), _text(rng), "C:" + chr(92) + "logs" + chr(92) + "app.log", "/var/" + "d" * 200 + "/app.log"]
    )


def _count(rng: random.Random) -> int:
    return rng.choice([0, 1, 7, rng.randrange(2**53), 2**53])


def _moment(rng: random.Random) -> datetime | None:
    kind = rng.randrange(3)
    if kind == 0:
        return None
    moment = datetime(2000, 1, 1) + timedelta(seconds=rng.randrange(0, 3 * 10**9), microseconds=rng.randrange(10**6))
    return moment if kind == 1 else moment.replace(tzinfo=UTC)


def _entry(rng: random.Random) -> DiffEntry:
    return DiffEntry(
        id=rng.choice(IDS),
        text=_text(rng),
        before_count=_count(rng),
        after_count=_count(rng),
        before_share=0.0,
        after_share=0.0,
        ratio=rng.choice([None, rng.uniform(0.0, 1e9), 2.0]),
        level=rng.choice(LEVELS),
        levels={},
        example=None,
        first_seen=_moment(rng),
        last_seen=_moment(rng),
    )


def _template(rng: random.Random) -> Template:
    return Template(rng.choice(IDS), _text(rng), _count(rng), None, None, None, rng.choice(LEVELS), {})


def _run(name: str, records: int, unparsed: int) -> RunSummary:
    return RunSummary(name, 1, records + unparsed, records, unparsed, 0, False, False)


def _options(rng: random.Random, report: str) -> dict[str, int]:
    options: dict[str, int] = {}
    if rng.random() < 0.8:
        options["top"] = rng.choice([*range(9), 20, 100, 10**6, 10**30])
    limit = LIMITS.get(report)
    if limit is not None and rng.random() < 0.6:
        high = 4000 if limit == "max_bytes" else 900
        options[limit] = rng.choice([rng.randrange(0, high), 10**6 if limit == "max_bytes" else 3000])
    return options


def build_cases() -> dict[str, Case]:
    """Return every case by id: ``(report, kind, result, options)`` in the order the digests are written."""
    analysis, diff = _bases()
    cases: dict[str, Case] = {}
    kinds: dict[str, AnalysisResult | DiffResult] = {"real-analysis": analysis, "real-diff": diff}
    for report in REPORTS:
        for label, result in kinds.items():
            if report == "junit" and label == "real-analysis":
                continue
            for top in (0, 1, 3, 5, 20, 100, 10**6):
                cases[f"{label}/{report}/top={top}"] = (report, label, result, {"top": top})
            limit = LIMITS.get(report)
            if limit is not None:
                step = 31 if limit == "max_bytes" else 11
                for value in range(0, 3200 if limit == "max_bytes" else 900, step):
                    cases[f"{label}/{report}/{limit}={value}"] = (report, label, result, {"top": 50, limit: value})
    rng = random.Random(2026)
    for number in range(RANDOM_CASES):
        pieces = [tuple(_entry(rng) for _ in range(rng.randrange(0, 7))) for _ in range(3)]
        hostile_diff = replace(
            diff,
            new_templates=pieces[0],
            changed=pieces[1],
            disappeared=pieces[2],
            unchanged=_count(rng),
            before=_run(_name(rng), rng.choice([0, 1, 7, 1234567]), 0),
            after=_run(_name(rng), rng.choice([0, 1, 7, 1234567, 10**12]), 0),
            warnings=tuple(_text(rng) for _ in range(rng.randrange(0, 3))),
        )
        items = tuple(sorted((_template(rng) for _ in range(rng.randrange(0, 8))), key=lambda t: -t.count))
        hostile_analysis = replace(
            analysis,
            templates=items,
            run=_run(_name(rng), rng.choice([0, 1, 7, 1234567, 10**12]), rng.choice([0, 3, 10**6])),
            warnings=tuple(_text(rng) for _ in range(rng.randrange(0, 3))),
        )
        for report in REPORTS:
            options = _options(rng, report)
            cases[f"random-{number}/{report}/diff"] = (report, "diff", hostile_diff, options)
            if report != "junit":
                cases[f"random-{number}/{report}/analysis"] = (report, "analysis", hostile_analysis, options)
    return cases


def fingerprints(render: Callable[[str, AnalysisResult | DiffResult, dict[str, int]], str]) -> dict[str, str]:
    """Return the SHA-256 of the text that ``render(report, result, options)`` gives for every case."""
    return {
        case_id: hashlib.sha256(render(report, result, options).encode("utf-8")).hexdigest()[:20]
        for case_id, (report, _kind, result, options) in build_cases().items()
    }


def current(report: str, result: AnalysisResult | DiffResult, options: dict[str, int]) -> str:
    """Render with the reporter of the installed logfold."""
    return get_reporter(report).render(result, **options)  # type: ignore[no-any-return]


def main() -> None:
    """Rewrite the golden file from the reporters of the installed logfold."""
    document: dict[str, Any] = {"cases": fingerprints(current)}
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN.write_bytes((json.dumps(document, indent=1) + "\n").encode("utf-8"))
    print(f"{len(document['cases'])} cases written to {GOLDEN}")


if __name__ == "__main__":
    main()
