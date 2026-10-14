"""Download the samples of other projects that ``formats_external.py`` checks, with pinned revisions and SHA-256.

The samples are logs that other people wrote, some with an expected parse that they wrote next to them. Nothing of theirs
is committed: ``external_samples.json`` lists each file (source, path in the repository, the format that reads it, how the
expected result is known); a source has a pinned commit and a licence. Files go to ``bench/data/formats/external/``
(git-ignored), and every download is checked against the SHA-256 in the manifest.

Usage: ``python bench/validate/external_samples.py [--pin]`` downloads everything missing; ``--pin`` also writes the digest
of every file that has none yet (the first time a sample is added), after you have read the file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MANIFEST = Path(__file__).with_name("external_samples.json")
CACHE = Path(__file__).resolve().parents[1] / "data" / "formats" / "external"
RAW = "https://raw.githubusercontent.com"
EXPECTED_SUFFIX = "-expected.json"
EXPECTED = "expected"


@dataclass(frozen=True)
class Sample:
    """One log of another project and how its expected parse is known."""

    source: str
    format: str
    path: str
    log: Path
    oracle: str
    expected: Path | None = None
    options: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        """Return a short name for tables: the project, the module (when there is one) and the file."""
        parts = self.path.split("/")
        if len(parts) > 3 and parts[:2] == ["filebeat", "module"]:
            return f"{parts[2]}/{parts[-1]}"
        return f"{self.source}:{parts[-1]}"


def load_manifest() -> dict[str, Any]:
    """Read the manifest."""
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def url(source: dict[str, str], path: str) -> str:
    """Return the address of a file at the pinned commit."""
    return f"{RAW}/{source['repo']}/{source['commit']}/{path}"


def digest(data: bytes) -> str:
    """Return the SHA-256 of a file."""
    return hashlib.sha256(data).hexdigest()


def download(address: str) -> bytes:
    """Download one file; the sources are plain HTTPS and the result is checked against the manifest by the caller."""
    with urllib.request.urlopen(address, timeout=60) as response:
        return response.read()


def fetch_file(source: dict[str, str], name: str, path: str, digests: dict[str, str], pin: bool) -> tuple[Path, bool]:
    """Make one file present in the cache and equal to its pinned digest; return it and whether a digest was added."""
    target = CACHE / name / path
    if not target.exists() or (digests.get(path) and digest(target.read_bytes()) != digests[path]):
        data = download(url(source, path))
        if path in digests and digest(data) != digests[path]:
            raise RuntimeError(f"{path} does not match the pinned SHA-256")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    if path in digests:
        return target, False
    if not pin:
        raise RuntimeError(f"{path} has no pinned SHA-256: read the file, then run with --pin")
    digests[path] = digest(target.read_bytes())
    return target, True


def fetch(pin: bool = False) -> list[Sample]:
    """Make sure every sample is in the cache and matches its digest; return them.

    Raises:
        RuntimeError: If a downloaded file does not match the digest of the manifest.
    """
    manifest = load_manifest()
    samples: list[Sample] = []
    changed = False
    for entry in manifest["samples"]:
        source = manifest["sources"][entry["source"]]
        digests: dict[str, str] = entry.setdefault("sha256", {})
        oracle = entry.get("oracle", EXPECTED)
        log, added = fetch_file(source, entry["source"], entry["path"], digests, pin)
        changed |= added
        expected = None
        if oracle == EXPECTED:
            expected, added = fetch_file(source, entry["source"], entry["path"] + EXPECTED_SUFFIX, digests, pin)
            changed |= added
        samples.append(
            Sample(entry["source"], entry["format"], entry["path"], log, oracle, expected, entry.get("options", {}))
        )
    if changed:
        MANIFEST.write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8", newline="\n")
    return samples


def main() -> None:
    """Download and verify all the samples."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--pin", action="store_true", help="write the digest of files that have none")
    args = parser.parse_args()
    samples = fetch(args.pin)
    print(f"{len(samples)} samples in {CACHE}")


if __name__ == "__main__":
    main()
