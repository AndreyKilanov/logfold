"""Deterministic benchmark datasets.

Large real-world corpora (Loghub-2.0) could not be downloaded in the environment that produced the first results, so
the datasets are generated: Loghub-2k seed lines with randomised numeric fields, synthetic access and application logs,
and an adversarial high-cardinality set. The generator is seeded; the same arguments give byte-identical files.

Usage::

    python bench/gen.py --out bench/data --size-mb 100
"""

from __future__ import annotations

import argparse
import random
import re
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

LOGHUB_RAW = "https://raw.githubusercontent.com/logpai/loghub/master/{name}/{name}_2k.log"
LOGHUB_SEEDS = ("HDFS", "Apache", "OpenSSH", "Linux", "Hadoop", "Zookeeper", "Spark", "Thunderbird")
DIGITS = re.compile(r"\d+")


def fetch_loghub(name: str, cache: Path) -> list[str]:
    """Return the lines of a Loghub-2k sample, downloading it once."""
    path = cache / f"{name}_2k.log"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(LOGHUB_RAW.format(name=name), path)
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def perturb(line: str, rng: random.Random) -> str:
    """Randomise the long numbers of a line (ids, ports, addresses) and keep short ones.

    Digit runs of one or two characters (days, months, hours, minutes, seconds, small counters) stay as they are, so dates
    and times remain real: in real logs they change slowly, and randomising them per line would create an artificial
    explosion of distinct tokens. Runs of three or more digits get random digits of the same length.
    """

    def swap(match: re.Match[str]) -> str:
        text = match.group(0)
        if len(text) <= 2:
            return text
        return "".join(rng.choice("0123456789") for _ in text)

    return DIGITS.sub(swap, line)


def loghub_pool(rng: random.Random, cache: Path, variants: int = 40) -> list[str]:
    pool: list[str] = []
    for name in LOGHUB_SEEDS:
        seed = fetch_loghub(name, cache)
        for _ in range(variants):
            pool.extend(perturb(line, rng) for line in seed)
    return pool


def nginx_pool(rng: random.Random, size: int = 600_000, variant: str = "a") -> list[str]:
    methods = ("GET", "GET", "GET", "POST", "PUT", "DELETE")
    pages = ("/", "/login", "/static/app.js", "/static/site.css", "/api/items", "/api/users", "/health")
    if variant == "b":
        pages += ("/api/export", "/api/export", "/checkout")
    agents = ("curl/8.4.0", "Mozilla/5.0 (X11; Linux x86_64)", "python-requests/2.31", "Go-http-client/2.0")
    lines = []
    for i in range(size):
        path = rng.choice(pages)
        if path.startswith("/api") and rng.random() < 0.7:
            path += f"/{rng.randrange(100_000)}"
        stamp = f"04/Oct/2026:{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d} +0000"
        weights = (70, 4, 10, 8, 5, 3) if variant == "a" else (55, 4, 10, 8, 18, 5)
        status = rng.choices((200, 301, 304, 404, 500, 502), weights)[0]
        lines.append(
            f"10.{rng.randrange(256)}.{rng.randrange(256)}.{rng.randrange(1, 255)} - - [{stamp}] "
            f'"{rng.choice(methods)} {path} HTTP/1.1" {status} {rng.randrange(120, 90_000)} "-" "{rng.choice(agents)}"'
        )
    return lines


def app_pool(rng: random.Random, size: int = 600_000, variant: str = "a") -> list[str]:
    services = ("auth", "billing", "search", "gateway", "worker", "scheduler")
    templates = [
        ("INFO", "user {user} logged in from {ip}"),
        ("INFO", "request {rid} completed in {ms}ms status={status}"),
        ("WARN", "slow query took {ms}ms on table orders_{n}"),
        ("ERROR", "failed to connect to {ip}:{port}: connection refused"),
        ("INFO", "cache miss for key session:{rid}"),
        ("DEBUG", "heartbeat from node-{n}"),
        ("INFO", "job {rid} scheduled for tenant t{n}"),
        ("ERROR", "payment {rid} declined: insufficient funds (balance={ms})"),
        ("WARN", "retry {n} of 5 for upstream {ip}"),
        ("INFO", "deployed version 2.{n}.{status} to {ip}"),
        ("FATAL", "out of memory while processing batch {rid}"),
        ("INFO", "gc pause {ms}ms heap={rid}MB"),
    ]
    if variant == "b":
        templates = [t for t in templates if "gc pause" not in t[1]]
        templates.append(("ERROR", "circuit breaker opened for upstream {ip}"))
        templates.append(("WARN", "queue depth {ms} exceeds limit on worker-{n}"))
    users = [f"user{n}" for n in range(500)]
    lines = []
    for i in range(size):
        level, text = rng.choice(templates)
        body = text.format(
            user=rng.choice(users),
            ip=f"10.0.{rng.randrange(256)}.{rng.randrange(1, 255)}",
            rid=rng.randrange(10**9),
            ms=rng.randrange(1, 5000),
            n=rng.randrange(1, 64),
            status=rng.choice((200, 201, 400, 500)),
            port=rng.choice((5432, 6379, 9200, 8080)),
        )
        stamp = f"2026-10-04T{(i // 3600) % 24:02d}:{(i // 60) % 60:02d}:{i % 60:02d}.{rng.randrange(1000):03d}Z"
        lines.append(f"{stamp} {level:<5} [{rng.choice(services)}] {body}")
    return lines


def highcard_pool(rng: random.Random, size: int = 400_000) -> list[str]:
    vocabulary = [f"{rng.choice('abcdefghijklmnopqrstuvwxyz')}{rng.getrandbits(40):x}" for _ in range(60_000)]
    lines = []
    for _ in range(size):
        words = [rng.choice(vocabulary) for _ in range(rng.randrange(6, 16))]
        lines.append(" ".join(words))
    return lines


def write_dataset(path: Path, pool: list[str], size_bytes: int, rng: random.Random) -> int:
    """Write shuffled passes over ``pool`` until the file reaches ``size_bytes``; return the number of lines."""
    written = 0
    count = 0
    order = list(range(len(pool)))
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        while written < size_bytes:
            rng.shuffle(order)
            for index in order:
                line = pool[index] + "\n"
                stream.write(line)
                written += len(line)
                count += 1
                if written >= size_bytes:
                    break
    return count


def datasets(cache: Path, variant: str) -> Iterator[tuple[str, Callable[[random.Random], list[str]]]]:
    yield "nginx", lambda rng: nginx_pool(rng, variant=variant)
    yield "app", lambda rng: app_pool(rng, variant=variant)
    yield "loghub", lambda rng: loghub_pool(rng, cache)
    yield "highcard", highcard_pool


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("bench/data"))
    parser.add_argument("--size-mb", type=int, default=100)
    parser.add_argument("--only", nargs="*", help="dataset names to generate")
    parser.add_argument("--variant", choices=("a", "b"), default="a", help="b = the 'after' run of a diff pair")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, build in datasets(args.out / "seeds", args.variant):
        if args.only and name not in args.only:
            continue
        suffix = "" if args.variant == "a" else "_b"
        target = args.out / f"{name}_{args.size_mb}mb{suffix}.log"
        if target.exists():
            print(f"{target} exists, skipping")
            continue
        rng = random.Random(f"logfold-bench-{name}-{args.variant}")
        pool = build(rng)
        lines = write_dataset(target, pool, args.size_mb << 20, rng)
        print(f"{target}: {lines:,} lines, {target.stat().st_size / 1e6:.0f} MB")


if __name__ == "__main__":
    main()
