"""The pipeline reports write exactly the text they wrote when the pure-Python reporters were the reference."""

from __future__ import annotations

import json

from conftest import requires_native
from golden_reports import GOLDEN, current, fingerprints

pytestmark = requires_native


def test_every_report_gives_the_golden_text_for_every_case() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    got = fingerprints(current)
    assert sorted(got) == sorted(golden)
    different = [case for case in golden if got[case] != golden[case]]
    assert different == [], f"{len(different)} of {len(golden)} cases differ, first: {different[:10]}"


def test_the_cases_cover_hostile_text_every_report_and_both_kinds() -> None:
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))["cases"]
    assert len(golden) > 1000
    for report in ("github-summary", "junit", "chat-message", "prometheus"):
        assert any(f"/{report}/" in case for case in golden), report
    assert any(case.endswith("/analysis") for case in golden)
    assert any(case.endswith("/diff") for case in golden)
