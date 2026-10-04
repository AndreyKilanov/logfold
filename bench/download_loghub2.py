"""Download Loghub-2.0 log files (an unofficial Hugging Face upload) for the benchmarks.

The official copy lives on Zenodo; this script uses the Hugging Face dataset ``bolu61/loghub_2`` (plain text, one log line
per line, no ground truth). The data is free for research with attribution to the Loghub authors; keep it local and do not
redistribute it. Downloads resume after an interruption and are verified by size and SHA-256.

Usage::

    python bench/download_loghub2.py --list
    python bench/download_loghub2.py hdfs spark thunderbird bgl
    python bench/download_loghub2.py --all --out bench/data/loghub2
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = "bolu61/loghub_2"
API = f"https://huggingface.co/api/datasets/{REPO}?blobs=true"
RESOLVE = f"https://huggingface.co/datasets/{REPO}/resolve/main/{{path}}"
DEFAULT_NAMES = ("hdfs", "spark", "thunderbird", "bgl")
CHUNK = 1 << 20


def remote_files() -> dict[str, tuple[str, int, str | None]]:
    """Return ``{short name: (repository path, size in bytes, sha256 or None)}`` of the text files."""
    with urllib.request.urlopen(API, timeout=60) as response:
        data = json.load(response)
    files: dict[str, tuple[str, int, str | None]] = {}
    for sibling in data["siblings"]:
        path = sibling["rfilename"]
        if not path.endswith(".txt"):
            continue
        digest = (sibling.get("lfs") or {}).get("sha256")
        files[Path(path).stem] = (path, int(sibling.get("size") or 0), digest)
    return files


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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help=f"files to download (default: {' '.join(DEFAULT_NAMES)})")
    parser.add_argument("--all", action="store_true", help="download every file (about 5 GB)")
    parser.add_argument("--list", action="store_true", help="list the available files and sizes")
    parser.add_argument("--out", type=Path, default=Path("bench/data/loghub2"))
    args = parser.parse_args()

    files = remote_files()
    if args.list:
        for name, (path, size, _digest) in sorted(files.items(), key=lambda item: -item[1][1]):
            print(f"{name:12} {size / 1e6:9.1f} MB  {path}")
        print(f"{'total':12} {sum(v[1] for v in files.values()) / 1e6:9.1f} MB")
        return 0

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
