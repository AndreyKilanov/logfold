"""Golden cases of the sequential engine: the cases, their serialisation and the command that regenerates the file.

``tests/fixtures/golden/sequential.json`` holds what the sequential strategy returned for every case below. It was
written by the pure-Python reference engine, which this file replaces as the second opinion on the Rust engine
(``docs/ALGORITHM.md``). Change it only together with a deliberate change of the algorithm:
``python tests/golden_cases.py`` rewrites it from the native engine.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import random
import tempfile
from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

import logfold
from corpora import CORPORA, write, write_corpus_dir
from logfold import MaskRule, MiningConfig

GOLDEN = Path(__file__).parent / "fixtures" / "golden" / "sequential.json"
MAX_KEPT_TEMPLATES = 100
Case = Callable[[Path, Path, str], Any]
"""``case(corpus_dir, work_dir, engine)`` runs the engine and returns plain JSON data."""


def jsonable(value: Any) -> Any:
    """Turn a result into plain JSON data, keeping the order of mappings."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {field.name: jsonable(getattr(value, field.name)) for field in dataclasses.fields(value)}
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def analysis_payload(result: logfold.AnalysisResult) -> dict[str, Any]:
    """Return the counters and the templates of ``result``, without the file name."""
    run = jsonable(result.run)
    del run["name"]
    return {"run": run, "templates": jsonable(list(result.templates))}


def digest_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the counters of ``payload`` and a fingerprint of everything else.

    Used for the cases whose full result is too large to keep in the repository.
    """
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "run": payload["run"],
        "templates": len(payload["templates"]),
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def compact(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep ``payload`` whole when it has few templates and fingerprint it otherwise."""
    return payload if len(payload["templates"]) <= MAX_KEPT_TEMPLATES else digest_payload(payload)


def wide_log(path: Path) -> None:
    """Write 4000 lines over a vocabulary of 400 words, which fills the leaves with many clusters."""
    rng = random.Random(77)
    vocabulary = [f"{rng.choice('abcdef')}{rng.getrandbits(18):x}" for _ in range(400)]
    shared = ["start", "stop", "retry", "ok"]
    lines = []
    for _ in range(4000):
        count = rng.randrange(3, 9)
        tokens = [rng.choice(shared) if rng.random() < 0.35 else rng.choice(vocabulary) for _ in range(count)]
        lines.append(" ".join(tokens))
    write(path, lines)


def crowded_log(path: Path, lines: int, seed: int) -> None:
    """Write lines with a constant first token and 40 families: big leaves and long shared index lists."""
    rng = random.Random(seed)
    out = []
    for _ in range(lines):
        length = rng.randint(6, 19)
        family = rng.randrange(40)
        words = ["-"]
        for position in range(1, length):
            kind = position % 5
            if kind == 0:
                words.append(f"s{position}x{rng.randrange(2)}")
            elif kind == 1:
                words.append(f"m{position}x{rng.randrange(30)}")
            elif (family + position) % 2 == 0:
                words.append(f"f{family}p{position}")
            else:
                words.append(f"r{position}x{rng.randrange(5000)}")
        out.append(" ".join(words))
    write(path, out)


def analysis(files: Callable[[Path], str | list[str]], **options: Any) -> Case:
    """Build a case that analyses the files and keeps the whole result."""

    def run(corpus: Path, _work: Path, engine: str) -> Any:
        result = logfold.analyze(files(corpus), engine=engine, strategy="sequential", **options)
        return compact(analysis_payload(result))

    return run


def corpus_file(name: str) -> Callable[[Path], str]:
    """Return the path of a corpus file inside the corpus directory."""
    return lambda corpus: str(corpus / name)


def generated(name: str, make: Callable[[Path], None], **options: Any) -> Case:
    """Build a case that writes a log into the work directory and analyses it."""

    def run(_corpus: Path, work: Path, engine: str) -> Any:
        path = work / f"{name.replace('/', '_')}.log"
        make(path)
        result = logfold.analyze(str(path), engine=engine, strategy="sequential", format="plain", **options)
        return compact(analysis_payload(result))

    return run


def diff_case(**options: Any) -> Case:
    """Build a case that compares the before and after logs of the corpus directory."""

    def run(corpus: Path, _work: Path, engine: str) -> Any:
        result = logfold.diff(
            str(corpus / "app_before.log"),
            str(corpus / "app_after.log"),
            engine=engine,
            strategy="sequential",
            format="app",
            **options,
        )
        return {
            "new": jsonable(result.new_templates),
            "disappeared": jsonable(result.disappeared),
            "changed": jsonable(result.changed),
            "unchanged": result.unchanged,
        }

    return run


def long_example(_corpus: Path, work: Path, engine: str) -> Any:
    """Analyse a record with a 3000-character word, whose example is cut on a character boundary."""
    path = work / "long_example.log"
    path.write_text("start " + "é" * 3000 + "\n", encoding="utf-8")
    result = logfold.analyze(str(path), engine=engine, strategy="sequential", format="plain")
    return analysis_payload(result)


def build_cases() -> dict[str, Case]:
    """Return every golden case by name."""
    cases: dict[str, Case] = {}
    for name, (_generate, fmt, multiline) in CORPORA.items():
        cases[f"corpus/{name}"] = analysis(corpus_file(f"{name}.log"), format=fmt, multiline=multiline or None)
    for name in ("app_crlf.log", "app_nonl.log"):
        cases[f"line_endings/{name}"] = analysis(corpus_file(name), format="app")
    options = [
        {"depth": 3},
        {"depth": 6},
        {"depth": 4, "sim_th": 0.0},
        {"depth": 4, "sim_th": 1.0},
        {"depth": 5, "sim_th": 0.7, "max_children": 2},
        {"depth": 4, "max_children": 1},
        {"max_templates": 1},
        {"max_templates": 4},
        {"max_templates": 5},
    ]
    for index, option in enumerate(options):
        cases[f"parameters/{index}"] = analysis(corpus_file("noisy.log"), format="plain", **option)
    mining = MiningConfig(
        delimiters=" \t\n\r,;=",
        masks=(MaskRule("user", r"user [a-z]+", "user <USER>"), MaskRule("num", r"\d+", "<N>", True)),
    )
    cases["custom_masks"] = analysis(corpus_file("app.log"), format="app", mining=mining)
    cases["multiple_files"] = analysis(lambda c: [str(c / "app.log"), str(c / "app_nonl.log")], format="app")
    cases["time_window"] = analysis(
        corpus_file("app.log"), format="app", since="2026-10-04T00:05:00Z", until="2026-10-04T00:15:00Z"
    )
    cases["long_example"] = long_example
    for sim_th in (0.1, 0.4, 0.7, 1.0):
        cases[f"wide/{sim_th}"] = generated(f"wide/{sim_th}", wide_log, sim_th=sim_th)
    for sim_th in (0.2, 0.4, 0.7, 0.95):
        cases[f"crowded/{sim_th}"] = generated(
            f"crowded/{sim_th}", lambda path: crowded_log(path, 12000, 5), mining=MiningConfig(sim_th=sim_th), masks=()
        )
    cases["diff/recount"] = diff_case()
    cases["diff/no_recount"] = diff_case(recount=False)
    return cases


CASES = build_cases()


def run_cases(engine: str) -> dict[str, Any]:
    """Run every case on ``engine`` in a scratch directory."""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw)
        corpus, work = root / "corpora", root / "work"
        corpus.mkdir()
        work.mkdir()
        write_corpus_dir(corpus)
        return {name: case(corpus, work, engine) for name, case in CASES.items()}


def main() -> None:
    """Rewrite the golden file from ``--engine`` (the native engine by default)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--engine", default="native", choices=("native", "python"))
    args = parser.parse_args()
    cases = run_cases(args.engine)
    GOLDEN.parent.mkdir(parents=True, exist_ok=True)
    document = {"generated_by": f"{args.engine} engine, logfold {logfold.__version__}", "cases": cases}
    GOLDEN.write_bytes((json.dumps(document, ensure_ascii=False, indent=1) + "\n").encode("utf-8"))
    print(f"{len(cases)} cases written to {GOLDEN}")


if __name__ == "__main__":
    main()
