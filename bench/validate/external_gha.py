"""Real GitHub Actions logs of this repository, as samples for ``formats_external.py``.

The raw log archive of a workflow run (``gh api repos/OWNER/REPO/actions/runs/ID/logs``) holds one file per job
(``N_<job>.txt``) in the form that ``github-actions`` reads: every line starts with a time, the first one with a byte order
mark. The logs expire after 90 days, so these samples are not pinned: the check takes the newest runs, two that passed and
one that failed (it has ``##[error]`` lines), whatever they are on the day.

Needs the ``gh`` command, signed in.
"""

from __future__ import annotations

import io
import json
import subprocess
import time
import zipfile

from external_samples import CACHE, Sample

REPOSITORY = "AndreyKilanov/logfold"
FORMAT = "github-actions"
OPTIONS = {
    "time_re": r"^\ufeff?(\S+Z) ",
    "level_re": r"##\[(error|warning|notice|debug)\]",
    "start_re": r"^\ufeff?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ",
}
PASSED, FAILED = 2, 1


def gh(*args: str) -> bytes:
    """Run ``gh`` and return its output; the download of a log archive is tried three times."""
    for attempt in range(3):
        done = subprocess.run(["gh", *args], capture_output=True, check=False)
        if done.returncode == 0:
            return done.stdout
        time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"gh {' '.join(args)} failed: {done.stderr.decode('utf-8', 'replace')[:300]}")


def pick_runs() -> list[int]:
    """Return the ids of the newest runs: some that passed and one that failed."""
    rows = json.loads(gh("run", "list", "--repo", REPOSITORY, "--limit", "60", "--json", "databaseId,conclusion,name"))
    runs = [row for row in rows if row["name"] == "CI"]
    chosen = [row["databaseId"] for row in runs if row["conclusion"] == "success"][:PASSED]
    return chosen + [row["databaseId"] for row in runs if row["conclusion"] == "failure"][:FAILED]


def samples() -> list[Sample]:
    """Download the runs and return one sample for each job log."""
    found: list[Sample] = []
    for run in pick_runs():
        folder = CACHE / "gha" / str(run)
        if not folder.exists():
            data = gh("api", f"repos/{REPOSITORY}/actions/runs/{run}/logs")
            folder.mkdir(parents=True)
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                for name in bundle.namelist():
                    if "/" not in name and name.endswith(".txt"):
                        safe = name.replace(" ", "_").replace("(", "").replace(")", "")
                        (folder / safe).write_bytes(bundle.read(name))
        for path in sorted(folder.glob("*.txt")):
            found.append(Sample("gha", FORMAT, f"run {run}/{path.name}", path, "lines", None, OPTIONS))
    return found
