"""Canary secrets: invented values planted in log lines must not survive the built-in mask sets anywhere."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import logfold
from conftest import requires_native
from corpora import write

pytestmark = requires_native

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJjYW5hcnkifQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
GOOGLE = "AIza" + "A1b2C3d4E5" * 3 + "F6g7H"
KEY_BLOCK = "-----BEGIN PRIVATE KEY-----MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7-----END PRIVATE KEY-----"

# (what the line says, the text that must not appear in any output)
CANARIES = [
    ("token {0} was issued", JWT),
    ("aws key {0} rotated", "AKIAIOSFODNN7EXAMPLE"),
    ("github {0} revoked", "ghp_1234567890abcdefghijklmnopqrstuvwxyz"),
    ("gitlab {0} revoked", "glpat-abcdefghij0123456789"),
    ("slack {0} posted", "xox" + "b-123456789012-1234567890123-abcdefghijklmnopqrstuvwx"),
    ("stripe {0} charged", "sk_live_abcdefghijklmnop1234"),
    ("google {0} quota", GOOGLE),
    ("npm {0} published", "npm_" + "a1B2c3D4e5" * 3 + "F6g7H8"),
    ("llm {0} billed", "sk-canary0123456789abcdefghij"),
    ("call failed Authorization: Basic {0}", "dXNlcjpwYXNzd29yZA=="),
    ("call failed Authorization: Bearer {0}", "0123456789abcdef0123456789abcdef"),
    ("retry with Bearer {0}", "0123456789abcdef0123456789abcdef"),
    ("connect postgres://admin:{0}@db.internal:5432/app", "hunter2canaryvalue"),
    ("login password={0} user=bob", "Sup3rS3cretCanary"),
    ("login api_key: {0}", "abcDEF123canary456"),
    ("login pwd: {0}", "pw1"),
    ("loaded {0}", "-----BEGIN RSA PRIVATE KEY-----"),
    ("loaded {0}", KEY_BLOCK),
    ("mail sent to {0}", "canary.user+tag@example.com"),
    ("call from {0}", "+44 20 7946 0958"),
    ("call from {0}", "+7 (495) 123-45-67"),
    ("call from {0}", "+442079460958"),
    ("call from {0}", "+1-202-555-0143"),
    ("charge card {0}", "4111 1111 1111 1111"),
    ("charge card {0}", "5555555555554444"),
    ("charge card {0}", "378282246310005"),
    ("charge card {0}", "6011000990139424"),
    ("charge card {0}", "3530111333300000"),
    ("charge card {0}", "30569309025904"),
    ("charge card {0}", "4000 0566 5566 5556"),
    ("transfer to {0}", "GB82 WEST 1234 5698 7654 32"),
    ("transfer to {0}", "DE89370400440532013000"),
    ("transfer to {0}", "FR1420041010050500013M02606"),
    ("transfer to {0}", "NL91ABNA0417164300"),
]


def lines_for(template: str, canary: str) -> list[str]:
    return [f"2026-10-04 10:00:{n:02d} INFO " + template.format(canary) + f" attempt {n}" for n in range(1, 4)]


@pytest.mark.parametrize(("template", "canary"), CANARIES, ids=[f"{i}" for i in range(len(CANARIES))])
def test_a_canary_is_in_no_output_once_the_sets_are_selected(tmp_path: Path, template: str, canary: str) -> None:
    log = write(tmp_path / "a.log", lines_for(template, canary))
    results = {}
    for examples in ("masked", "none"):
        results[examples] = logfold.analyze(
            str(log), format="plain", engine="native", masks=["secrets", "pii"], examples=examples
        )
    for examples, result in results.items():
        for reporter in ("json", "html", "text", "markdown", "csv"):
            assert canary not in result.render(reporter), (examples, reporter)
    json_state, binary_state = tmp_path / "s.json", tmp_path / "s.bin"
    logfold.analyze(str(log), format="plain", engine="native", masks=["secrets", "pii"], save_state=json_state)
    logfold.analyze(
        str(log),
        format="plain",
        engine="native",
        masks=["secrets", "pii"],
        save_state=binary_state,
        state_format="binary",
    )
    assert canary.encode("utf-8") not in json_state.read_bytes()
    assert canary.encode("utf-8") not in binary_state.read_bytes()


def test_the_canary_is_visible_without_the_sets_so_the_test_can_fail(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", lines_for("mail sent to {0}", "canary.user+tag@example.com"))
    result = logfold.analyze(str(log), format="plain", engine="native", examples="raw")
    assert "canary.user+tag@example.com" in result.render("json")
    default_state = tmp_path / "d.json"
    logfold.analyze(str(log), format="plain", engine="native", save_state=default_state)
    assert b"canary.user+tag@example.com" in default_state.read_bytes()


def test_raw_examples_still_hold_the_original_line(tmp_path: Path) -> None:
    log = write(tmp_path / "a.log", lines_for("mail sent to {0}", "canary.user+tag@example.com"))
    result = logfold.analyze(str(log), format="plain", engine="native", masks=["pii"])
    assert "<EMAIL>" in result.templates[0].text
    assert "canary.user+tag@example.com" in json.dumps(result.templates[0].example)


def test_text_that_looks_like_a_secret_but_is_not_one_is_left_alone(tmp_path: Path) -> None:
    benign = [
        "Bearer authentication is enabled",
        "basic configuration loaded",
        "token count = 12 tokens",
        "tokenizer: bert-base",
        "max_tokens=500",
        "timestamp 1728900000000 elapsed 1728900000123456789",
        "version +2026-10-04 build 7",
        "offset +0530 zone",
        "card number 4111 1111 1111 1112 failed the check",
        "ref GB82 WEST 1234 5698 7654 33 is not valid",
        "see https://example.com/path?x=1",
        "user=alice@localhost",
        "pass=1 fail=0",
    ]
    log = write(tmp_path / "b.log", benign)
    plain = logfold.analyze(str(log), format="plain", engine="native", examples="none")
    masked = logfold.analyze(str(log), format="plain", engine="native", masks=["secrets", "pii"], examples="none")
    before = sorted(t.text for t in plain.templates)
    after = sorted(t.text for t in masked.templates)
    assert before == after
