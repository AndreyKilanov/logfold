"""The shell of the GitHub Action and of the GitLab template, run for real with the installed ``logfold``.

The steps are read from ``action.yml`` and ``ci/gitlab/logfold.yml`` and executed with bash, so a flag that the CLI no
longer accepts (or a baseline kept across other masks) fails here and not in the pipeline of a user.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vX7zA9cE1fG3hI5"
MASK_FILE = json.dumps(
    {"name": "orders", "version": 1, "rules": [{"name": "order", "pattern": r"\bORD-[0-9]{6}\b", "token": "<ORDER>"}]}
)


def find_bash() -> str | None:
    if sys.platform == "win32":
        git = shutil.which("git")  # the bash of Git for Windows, not the one of WSL that may stand first in PATH
        for parent in Path(git).parents if git else ():
            for relative in ("bin/bash.exe", "usr/bin/bash.exe"):
                if (parent / relative).is_file():
                    return str(parent / relative)
        return None
    return shutil.which("bash")


BASH = find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="bash is not available")


def environment(**extra: str) -> dict[str, str]:
    env = dict(os.environ)
    env["PATH"] = str(Path(sys.executable).parent) + os.pathsep + env["PATH"]
    env.update(CI_DEFAULT_BRANCH="main", CI_COMMIT_BRANCH="main", GITHUB_SHA="1a2b3c4d5e", GITHUB_REF_NAME="feature")
    env.update(extra)
    return env


def run_script(script: str, folder: Path, **env: str) -> subprocess.CompletedProcess[str]:
    path = folder / "step.sh"
    path.write_text(script, encoding="utf-8", newline="\n")
    assert BASH is not None
    return subprocess.run(
        [BASH, str(path)],
        cwd=folder,
        env=environment(**env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def action_step(step_id: str) -> str:
    steps = yaml.safe_load((ROOT / "action.yml").read_text(encoding="utf-8"))["runs"]["steps"]
    return next(step["run"] for step in steps if step.get("id") == step_id)


def gitlab_script() -> str:
    job = yaml.safe_load((ROOT / "ci" / "gitlab" / "logfold.yml").read_text(encoding="utf-8"))[".logfold"]
    lines = job["script"][0].splitlines()
    return "\n".join(line for line in lines if "pip install" not in line)


def outputs(path: Path) -> dict[str, str]:
    pairs = (line.split("=", 1) for line in path.read_text(encoding="utf-8").splitlines() if "=" in line)
    return dict(pairs)


@pytest.fixture
def logs(tmp_path: Path) -> Path:
    base = []
    for i in range(1, 7):
        base.append(f"2026-10-14 10:00:0{i} INFO user login ok id={i}")
        base.append(f"2026-10-14 10:00:1{i} ERROR call failed with key {TOKEN} order ORD-12345{i} attempt {i}")
    (tmp_path / "base.log").write_text("\n".join(base) + "\n", encoding="utf-8")
    new = f"2026-10-14 10:01:00 ERROR new failure for ORD-999999 with key {TOKEN} in module x"
    (tmp_path / "cur.log").write_text("\n".join([*base, new]) + "\n", encoding="utf-8")
    (tmp_path / "orders.json").write_text(MASK_FILE, encoding="utf-8")
    return tmp_path


def gitlab(folder: Path, log: str, **variables: str) -> subprocess.CompletedProcess[str]:
    defaults = {"LOGFOLD_LOG": log, "LOGFOLD_EXAMPLES": "masked", "LOGFOLD_FAIL_ON": "--fail-on-new-alerts"}
    return run_script(gitlab_script(), folder, **{**defaults, **variables})


def test_gitlab_baseline_is_kept_per_masks(logs: Path) -> None:
    first = gitlab(logs, "base.log")
    assert first.returncode == 0, first.stderr
    assert (logs / ".logfold" / "baseline.masks").read_text().strip() == "nomasks"

    other = gitlab(logs, "base.log", LOGFOLD_MASKS="secrets")
    assert other.returncode == 0, other.stderr
    assert "other masks" in other.stdout
    assert (logs / ".logfold" / "baseline.masks").read_text().startswith("m")

    with_file = gitlab(logs, "base.log", LOGFOLD_MASKS="secrets", LOGFOLD_MASKS_FILE="orders.json")
    assert "other masks" in with_file.stdout  # a file changes the choice too

    found = gitlab(logs, "cur.log", LOGFOLD_MASKS="secrets", LOGFOLD_MASKS_FILE="orders.json")
    assert "other masks" not in found.stdout
    assert found.returncode == 2, found.stderr
    html = (logs / ".logfold" / "diff.html").read_text(encoding="utf-8")
    assert TOKEN not in html
    assert "ORD-999999" not in html


def test_gitlab_branch_with_other_masks_leaves_the_shared_baseline_alone(logs: Path) -> None:
    gitlab(logs, "base.log")
    kept = (logs / ".logfold" / "baseline.json").read_bytes()

    branch = gitlab(logs, "cur.log", LOGFOLD_MASKS="secrets", CI_COMMIT_BRANCH="feature")
    assert branch.returncode == 0, branch.stderr
    assert "other masks" in branch.stdout
    assert (logs / ".logfold" / "baseline.json").read_bytes() == kept
    assert (logs / ".logfold" / "baseline.masks").read_text().strip() == "nomasks"


def test_gitlab_without_masks_keeps_the_token_in_the_template(logs: Path) -> None:
    gitlab(logs, "base.log")
    found = gitlab(logs, "cur.log")
    assert found.returncode == 2
    assert TOKEN in (logs / ".logfold" / "diff.html").read_text(encoding="utf-8")


def action(
    folder: Path, baseline: str, masks: str = "", masks_file: str = ""
) -> tuple[subprocess.CompletedProcess[str], str]:
    out, summary = folder / "out.txt", folder / "summary.md"
    out.write_text("", encoding="utf-8")
    summary.write_text("", encoding="utf-8")
    choose = run_script(
        action_step("masks"), folder, INPUT_MASKS=masks, INPUT_MASKS_FILE=masks_file, GITHUB_OUTPUT=str(out)
    )
    if choose.returncode != 0:
        return choose, ""
    chosen = outputs(out)
    result = run_script(
        action_step("diff"),
        folder,
        INPUT_LOG="cur.log",
        INPUT_BASELINE=baseline,
        INPUT_FAIL_ON="new-alerts",
        INPUT_LEVEL="",
        INPUT_FORMAT="auto",
        INPUT_EXAMPLES="masked",
        INPUT_MASKS=masks,
        MASK_FILES=chosen.get("files", ""),
        INPUT_HTML="report",
        CACHED_BASELINE=str(folder / "cache" / "baseline.json"),
        WORK=str(folder / "work"),
        GITHUB_OUTPUT=str(out),
        GITHUB_STEP_SUMMARY=str(summary),
    )
    return result, summary.read_text(encoding="utf-8")


def save_analysis(folder: Path, name: str, *flags: str) -> None:
    command = [
        sys.executable,
        "-m",
        "logfold",
        "analyze",
        "base.log",
        "--examples",
        "masked",
        "--out",
        name,
        "-q",
        *flags,
    ]
    subprocess.run(command, cwd=folder, env=environment(), check=True, capture_output=True)


@pytest.mark.parametrize("baseline", ["base.log", "cache"])
def test_action_hides_the_masked_values(logs: Path, baseline: str) -> None:
    flags = ("--masks", "secrets", "--masks-file", "orders.json")
    if baseline == "cache":
        (logs / "cache").mkdir()
        save_analysis(logs, "cache/baseline.json", *flags)
        baseline = ""
    result, summary = action(logs, baseline, masks="secrets", masks_file="orders.json")
    assert result.returncode == 0, result.stderr
    assert outputs(logs / "out.txt")["exit-code"] == "2"
    assert "<KEY>" in summary
    assert "<ORDER>" in summary
    assert TOKEN not in summary
    assert "ORD-999999" not in summary


@pytest.mark.parametrize("baseline", ["base.log", "base.json"])
def test_action_compares_a_log_or_a_saved_analysis_without_masks(logs: Path, baseline: str) -> None:
    if baseline.endswith(".json"):
        save_analysis(logs, baseline)
    result, summary = action(logs, baseline)
    assert result.returncode == 0, result.stderr
    assert outputs(logs / "out.txt")["status"] == "found"
    assert TOKEN in summary


def test_action_cache_scope_follows_the_masks(logs: Path) -> None:
    scopes = []
    for masks, masks_file in (("", ""), ("secrets", ""), ("secrets,pii", ""), ("secrets", "orders.json")):
        out = logs / "scope.txt"
        out.write_text("", encoding="utf-8")
        run = run_script(
            action_step("masks"), logs, INPUT_MASKS=masks, INPUT_MASKS_FILE=masks_file, GITHUB_OUTPUT=str(out)
        )
        assert run.returncode == 0, run.stderr
        scopes.append(outputs(out)["scope"])
    assert scopes[0] == "nomasks"
    assert len(set(scopes)) == len(scopes)
    assert all(scope.startswith("m") for scope in scopes[1:])


@pytest.mark.parametrize(("masks", "masks_file"), [("se cret", ""), ("secrets;x", ""), ("", "nope.json")])
def test_action_refuses_bad_masks(logs: Path, masks: str, masks_file: str) -> None:
    result, _ = action(logs, "base.log", masks=masks, masks_file=masks_file)
    assert result.returncode != 0
    assert "::error::" in result.stdout
