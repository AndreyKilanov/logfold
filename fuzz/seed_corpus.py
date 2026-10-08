"""Writes the seed corpus of the fuzz targets from real files: states saved by `analyze` and a gzip log.

Run it from the repository root with logfold installed: `python fuzz/seed_corpus.py`. The seeds are the part of a file
that the target fuzzes: a target adds the magic bytes and the checksum itself.
"""

from __future__ import annotations

import gzip
import tempfile
from pathlib import Path

import logfold

CORPUS = Path(__file__).parent / "corpus"
BINARY_MAGIC_BYTES = 8
CHECKSUM_BYTES = 32


def log_text(lines: int) -> str:
    """Builds a small log with a few families of messages."""
    rows = []
    for n in range(lines):
        family = n % 4
        if family == 0:
            rows.append(f"2026-10-04T12:00:{n % 60:02d}Z INFO user u{n % 17} logged in from 10.0.{n % 8}.{n % 250}")
        elif family == 1:
            rows.append(f"2026-10-04T12:00:{n % 60:02d}Z WARN disk usage {50 + n % 40}% on /dev/sda{n % 3}")
        elif family == 2:
            rows.append(f"2026-10-04T12:00:{n % 60:02d}Z ERROR request {n} failed with status {500 + n % 4}")
        else:
            rows.append(f"2026-10-04T12:00:{n % 60:02d}Z INFO cache miss for key k{n % 31}")
    return "\n".join(rows) + "\n"


def write_seed(target: str, name: str, data: bytes) -> None:
    """Stores one seed of a target."""
    folder = CORPUS / target
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)


def main() -> None:
    """Saves states of two sizes in both forms and a gzip log, and cuts the seeds out of them."""
    with tempfile.TemporaryDirectory() as work:
        for size in (4, 400):
            log = Path(work) / f"log{size}.log"
            log.write_text(log_text(size), encoding="utf-8", newline="\n")
            for state_format in ("json", "binary"):
                saved = Path(work) / f"state{size}.{state_format}"
                logfold.analyze(str(log), format="plain", save_state=saved, state_format=state_format)
                raw = saved.read_bytes()
                if state_format == "json":
                    header, body, _ = raw.split(b"\n")[:3]
                    write_seed("state_json", f"seed_{size}", header + b"\n" + body)
                else:
                    write_seed("state_binary", f"seed_{size}", raw[BINARY_MAGIC_BYTES:-CHECKSUM_BYTES])
        compressed = gzip.compress(log_text(400).encode("utf-8"), mtime=0)
        write_seed("gzip_lines", "seed_gzip", compressed[2:])
        first, second = gzip.compress(b"a\n", mtime=0), gzip.compress(b"b\n", mtime=0)
        write_seed("gzip_lines", "seed_two_members", first[2:] + second)


if __name__ == "__main__":
    main()
