"""Download Loghub-2.0 log files (an unofficial Hugging Face upload) for the benchmarks.

The official copy lives on Zenodo (https://zenodo.org/record/8275861); this script uses the Hugging Face dataset
``bolu61/loghub_2`` (plain text, one log line per line, no ground truth) at the **pinned revision** below, so the files
and their SHA-256 do not change under a benchmark. The data is free for research with attribution to the Loghub authors
(Jiang et al., ISSTA 2024, arXiv:2308.10828; Zhu et al., ISSRE 2023, arXiv:2008.06448); keep it local and do not
redistribute it. Downloads resume after an interruption and are verified by size and the pinned SHA-256.

Usage::

    python bench/download_loghub2.py --list
    python bench/download_loghub2.py hdfs spark thunderbird bgl
    python bench/download_loghub2.py --all --out bench/data/loghub2
    python bench/download_loghub2.py --verify              # check the files you already have
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help=f"files to download (default: {' '.join(DEFAULT_NAMES)})")
    parser.add_argument("--all", action="store_true", help="download every file (about 5 GB)")
    parser.add_argument("--list", action="store_true", help="list the available files and sizes")
    parser.add_argument("--verify", action="store_true", help="check the downloaded files against the pinned SHA-256")
    parser.add_argument("--out", type=Path, default=Path("bench/data/loghub2"))
    args = parser.parse_args()

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


if __name__ == "__main__":
    raise SystemExit(main())
