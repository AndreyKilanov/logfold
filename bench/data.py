"""Inputs of the benchmarks: seeded generated logs, and the four large real logs.

``make`` writes deterministic datasets (the same arguments give byte-identical files): ``nginx``, ``app``, ``loghub`` (Loghub-2k
seed lines with randomised numbers) and ``highcard`` (adversarial: a huge number of distinct templates); ``--variant b`` writes
the "after" run of a diff pair::

    python bench/data.py make --size-mb 100
    python bench/data.py make --size-mb 100 --variant b --only nginx app

``loghub2`` downloads Loghub-2.0 (an unofficial Hugging Face upload) at a pinned revision and checks size and SHA-256. The official
copy lives on Zenodo (https://zenodo.org/record/8275861). The data is free for research with attribution to the Loghub authors
(Jiang et al., ISSTA 2024, arXiv:2308.10828; Zhu et al., ISSRE 2023, arXiv:2008.06448); keep it local and do not redistribute it.
Downloads resume after an interruption::

    python bench/data.py loghub2 --list
    python bench/data.py loghub2 hdfs spark thunderbird bgl
    python bench/data.py loghub2 --verify

Files go to ``bench/data/`` (git-ignored).
"""

from __future__ import annotations

import argparse
import hashlib
import random
import re
import sys
import time
import urllib.error
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


REPO = "bolu61/loghub_2"
REVISION = "4a98d3eb30522891b340609d17fa34709a1d44d2"
ZENODO = "https://zenodo.org/record/8275861"
RESOLVE = f"https://huggingface.co/datasets/{REPO}/resolve/{REVISION}/{{path}}"
DEFAULT_NAMES = ("hdfs", "spark", "thunderbird", "bgl")
CHUNK = 1 << 20

# {short name: (path in the repository, size in bytes, SHA-256)} at REVISION, taken from the Hugging Face API
# (``/api/datasets/bolu61/loghub_2/revision/<REVISION>?blobs=true``). Downloads and ``--verify`` are checked against it.
PINNED_FILES: dict[str, tuple[str, int, str]] = {
    "apache": ("data/apache.txt", 4975683, "3b1794121bce3c8b127d3cf3aa5efbed9690fb056c9016cb5e842ca7ef89aec1"),
    "bgl": ("data/bgl.txt", 719447452, "1bd8cb4a8b163b5085d21d8e0d4cd844e01748cdcc0888c6380e0fb34ca85591"),
    "hadoop": ("data/hadoop.txt", 31887283, "55b0395991c5c9a3f2a261436cdb156c634cb065feca9e088b28e37431a368d5"),
    "hdfs": ("data/hdfs.txt", 1565682217, "e8987f909b97ce975d65f773a4e1eae7aadab455a38db2aa29ed30ae8b96f166"),
    "healthapp": ("data/healthapp.txt", 20483511, "2353081c14c370b877d533d38930e0b8eca8f4cf94ef9ea292842ec62f0e3cc0"),
    "hpc": ("data/hpc.txt", 32610624, "f10b07cd190ce4d03e4145fbde9c19ee296138bc30863b44558a193a79f66138"),
    "linux": ("data/linux.txt", 2135395, "9ef66a377aa89f23e646a91fbb5f8d656f60191c75176f01933d64afdad4fb0e"),
    "mac": ("data/mac.txt", 15437759, "55554ee59796414b6e5ea1e22fc97640ad4b901ccd5067185228dbc2b9f1eab7"),
    "openssh": ("data/openssh.txt", 70536064, "aecae85174ea0c4b324bb2076fa8f1452b23ecd1fed8e69ba3a0c6ec5452adb3"),
    "openstack": ("data/openstack.txt", 61407564, "220f1395a35138263eeda81ba8729f1e37e7be365339cfca9a28ccd94e04310d"),
    "proxifier": ("data/proxifier.txt", 2519391, "aa4dcae98629465899ead595449eaf1f4393eaa1948805095677c11e4740f695"),
    "spark": ("data/spark.txt", 1629352119, "74da349d7202a13194aa02ca2dd0ccb18a130656d002b94eb6b0e78e92bf6823"),
    "thunderbird": (
        "data/thunderbird.txt",
        886308864,
        "29847ee32db96aab25e10ddc0b7f119a7932e2a00fa23a0d1e106da6db1a1d42",
    ),
    "zookeeper": (
        "holdout/zookeeper.txt",
        10330307,
        "ac7459a7e4e5744fd8d7793486a8ce9a8c7e5a554bc90c4895ea8a1de213c372",
    ),
}


def remote_files() -> dict[str, tuple[str, int, str | None]]:
    """Return ``{short name: (repository path, size in bytes, sha256)}`` of the pinned revision."""
    return dict(PINNED_FILES)


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(CHUNK):
            digest.update(block)
    return digest.hexdigest()


def fetch(path: str, size: int, destination: Path) -> None:
    """Download ``path`` to ``destination``, resuming a partial file."""
    have = destination.stat().st_size if destination.exists() else 0
    if have == size:
        return
    if have > size:
        destination.unlink()
        have = 0
    headers = {"User-Agent": "logfold-bench"}
    if have:
        headers["Range"] = f"bytes={have}-"
    request = urllib.request.Request(RESOLVE.format(path=path), headers=headers)
    started = time.perf_counter()
    last_report = 0.0
    with urllib.request.urlopen(request, timeout=120) as response:
        mode = "ab" if have and response.status == 206 else "wb"
        written = have if mode == "ab" else 0
        with destination.open(mode) as stream:
            while block := response.read(CHUNK):
                stream.write(block)
                written += len(block)
                now = time.perf_counter()
                if now - last_report > 2:
                    last_report = now
                    rate = (written - have) / max(now - started, 1e-9) / 1e6
                    print(
                        f"  {destination.name}: {written / 1e6:8.0f} / {size / 1e6:.0f} MB ({rate:.0f} MB/s)",
                        flush=True,
                    )


def verify(folder: Path, names: list[str], files: dict[str, tuple[str, int, str | None]]) -> int:
    """Compare local files with the pinned size and SHA-256; return a process exit code."""
    status = 0
    for name in names:
        _path, size, digest = files[name]
        destination = folder / f"{name}.txt"
        if not destination.exists():
            print(f"{name}: missing")
            status = 1
        elif destination.stat().st_size != size or sha256_of(destination) != digest:
            print(f"{name}: DIFFERENT from the pinned revision {REVISION[:12]}")
            status = 1
        else:
            print(f"{name}: ok ({size / 1e6:.0f} MB, sha256 {str(digest)[:16]}...)")
    return status


def make(args: argparse.Namespace) -> None:
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


def loghub2(args: argparse.Namespace) -> int:
    files = remote_files()
    if args.list:
        for name, (path, size, _digest) in sorted(files.items(), key=lambda item: -item[1][1]):
            print(f"{name:12} {size / 1e6:9.1f} MB  {path}")
        print(f"{'total':12} {sum(v[1] for v in files.values()) / 1e6:9.1f} MB")
        return 0

    if args.verify:
        return verify(args.out, args.names or [n for n in sorted(files) if (args.out / f"{n}.txt").exists()], files)

    wanted = sorted(files) if args.all else (args.names or list(DEFAULT_NAMES))
    unknown = [name for name in wanted if name not in files]
    if unknown:
        print(f"unknown names: {', '.join(unknown)}; known: {', '.join(sorted(files))}", file=sys.stderr)
        return 2
    args.out.mkdir(parents=True, exist_ok=True)
    total = sum(files[name][1] for name in wanted)
    print(f"downloading {len(wanted)} files, {total / 1e9:.2f} GB, into {args.out}")
    for name in wanted:
        path, size, digest = files[name]
        destination = args.out / f"{name}.txt"
        print(f"{name}: {size / 1e6:.0f} MB")
        try:
            fetch(path, size, destination)
        except (urllib.error.URLError, OSError) as error:
            print(f"  failed: {error}; run the command again to resume", file=sys.stderr)
            return 1
        if destination.stat().st_size != size:
            print(f"  size mismatch for {destination}; run the command again to resume", file=sys.stderr)
            return 1
        if digest and sha256_of(destination) != digest:
            print(f"  checksum mismatch for {destination}; delete the file and run again", file=sys.stderr)
            return 1
        print("  ok")
    return 0


def parser() -> argparse.ArgumentParser:
    """The command line."""
    main = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = main.add_subparsers(dest="what", required=True)
    first = sub.add_parser("make", help="generate the seeded datasets")
    first.add_argument("--out", type=Path, default=Path("bench/data"))
    first.add_argument("--size-mb", type=int, default=100)
    first.add_argument("--only", nargs="*", help="dataset names to generate")
    first.add_argument("--variant", choices=("a", "b"), default="a", help="b = the 'after' run of a diff pair")
    first.set_defaults(run=make)
    second = sub.add_parser("loghub2", help="download the four large real logs")
    second.add_argument("names", nargs="*", help=f"files to download (default: {' '.join(DEFAULT_NAMES)})")
    second.add_argument("--all", action="store_true", help="download every file (about 5 GB)")
    second.add_argument("--list", action="store_true", help="list the available files and sizes")
    second.add_argument("--verify", action="store_true", help="check the downloaded files against the pinned SHA-256")
    second.add_argument("--out", type=Path, default=Path("bench/data/loghub2"))
    second.set_defaults(run=loghub2)
    return main


def main() -> int:
    """Run the chosen subcommand."""
    args = parser().parse_args()
    return int(args.run(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
