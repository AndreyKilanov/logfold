"""Layered masking and checks: the Python reference and the native masker must give the same text."""

from __future__ import annotations

from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from logfold import MaskRule
from logfold.config import DEFAULT_MASKS
from logfold.ext import resolve_masks
from logfold.ext.masks import Masker, ReferenceMasker, iban_valid, luhn_valid

CARD = MaskRule("card", r"\b(?:\d{4}[ -]){3}\d{1,7}\b|\b\d{13,19}\b", "<CARD>", True, "luhn")
IBAN = MaskRule("iban", r"\b[A-Z]{2}\d{2}(?:[A-Z0-9]{11,30}|(?: [A-Z0-9]{4}){2,7})\b", "<IBAN>", True, "iban")
EMAIL = MaskRule("email", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "<EMAIL>", True)
LAYERED = (EMAIL, CARD, IBAN, *DEFAULT_MASKS)


def masked(text: str, rules: tuple[MaskRule, ...] = LAYERED) -> str:
    return ReferenceMasker(rules).mask(text)


@pytest.mark.parametrize("number", ["4111 1111 1111 1111", "5500-0000-0000-0004", "378282246310005", "4222222222222"])
def test_luhn_accepts_public_test_cards(number: str) -> None:
    assert luhn_valid(number)


@pytest.mark.parametrize("number", ["4111 1111 1111 1112", "4111 1111 1111 111x", "000000000000", "", "1234", "4" * 20])
def test_luhn_rejects_the_rest(number: str) -> None:
    assert not luhn_valid(number)


@pytest.mark.parametrize(
    "number",
    ["GB82 WEST 1234 5698 7654 32", "DE89370400440532013000", "FR1420041010050500013M02606", "NL91 ABNA 0417 1643 00"],
)
def test_iban_accepts_public_test_numbers(number: str) -> None:
    assert iban_valid(number)


@pytest.mark.parametrize(
    "number", ["GB82 WEST 1234 5698 7654 33", "1282WEST12345698765432", "GB82", "GB82WEST1234569876543!", ""]
)
def test_iban_rejects_the_rest(number: str) -> None:
    assert not iban_valid(number)


def test_a_selected_rule_runs_before_the_default_rules() -> None:
    assert masked("card 4111 1111 1111 1111 ok 12") == "card <CARD> ok <NUM>"


def test_a_candidate_that_fails_its_check_is_left_to_the_default_rules() -> None:
    assert masked("pay 4111 1111 1111 1112 now") == "pay <NUM> <NUM> <NUM> <NUM> now"


def test_the_search_goes_on_after_a_rejected_candidate() -> None:
    assert masked("4111 1111 1111 1112 then 4111 1111 1111 1111") == "<NUM> <NUM> <NUM> <NUM> then <CARD>"


def test_a_list_without_the_default_rules_is_one_layer() -> None:
    assert masked("bob@example.com 4111111111111111 12", (EMAIL, CARD)) == "<EMAIL> <CARD> 12"


def test_text_between_matches_is_masked_by_the_default_rules_alone() -> None:
    assert masked("a 12 bob@example.com 7 10.0.0.1") == "a <NUM> <EMAIL> <NUM> <IP>"


NATIVE_SAMPLES = [
    "user bob@example.com paid with 4111 1111 1111 1111 on 2026-10-04 12:00:01",
    "pay 4111 1111 1111 1112 now from 10.0.0.1:80",
    "iban GB82 WEST 1234 5698 7654 32 and DE89370400440532013000 and GB82 WEST 1234 5698 7654 33",
    "4111 1111 1111 1112 then 4111 1111 1111 1111 then 12",
    "no secrets here, only 12 numbers and /var/log/app.log",
    "mail a@b.co,c@d.org;e@f.net 0x1f 3.14",
    "id 123e4567-e89b-12d3-a456-426614174000 mail x.y@z.example.com",
    "x" * 40 + " bob@example.com " + "y" * 40,
]


def native_text(text: str, rules: tuple[MaskRule, ...], tmp_path: Path) -> str:
    path = tmp_path / "one.log"
    path.write_text(text + "\n", encoding="utf-8")
    result = logfold.analyze(str(path), format="plain", engine="native", strategy="sequential", masks=list(rules))
    return result.templates[0].text


@requires_native
@pytest.mark.parametrize("text", NATIVE_SAMPLES)
def test_native_layers_match_the_python_reference(text: str, tmp_path: Path) -> None:
    assert native_text(text, LAYERED, tmp_path) == " ".join(masked(text).split())


@requires_native
@pytest.mark.parametrize("text", NATIVE_SAMPLES)
def test_the_built_in_sets_match_the_python_reference(text: str, tmp_path: Path) -> None:
    rules = resolve_masks(["all"])
    assert native_text(text, rules, tmp_path) == " ".join(masked(text, rules).split())


PIECES = st.sampled_from(
    [
        "4111 1111 1111 1111",
        "4111 1111 1111 1112",
        "5500-0000-0000-0004",
        "GB82 WEST 1234 5698 7654 32",
        "DE89370400440532013000",
        "bob@example.com",
        "Authorization: Bearer abcdef1234567890abcdef",
        "password=hunter2",
        "postgres://u:p4ss@db:5432/x",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
        "AKIAIOSFODNN7EXAMPLE",
        "+44 20 7946 0958",
        "10.0.0.1:80",
        "2026-10-04 12:00:01Z",
        "/var/log/app.log",
        "0xdead",
        "123",
        "token",
        "=",
        ":",
        "x",
    ]
)


@requires_native
@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(pieces=st.lists(PIECES, min_size=1, max_size=8), separator=st.sampled_from([" ", "  ", ", ", "; "]))
def test_native_and_python_agree_on_random_lines(
    pieces: list[str], separator: str, tmp_path_factory: pytest.TempPathFactory
) -> None:
    rules = resolve_masks(["all"])
    text = separator.join(pieces)
    tmp_path = tmp_path_factory.mktemp("layers")
    assert native_text(text, rules, tmp_path) == " ".join(masked(text, rules).split())


@requires_native
@pytest.mark.parametrize("text", NATIVE_SAMPLES)
def test_the_native_masker_class_matches_the_reference_on_samples(text: str) -> None:
    for rules in (LAYERED, resolve_masks(["all"]), DEFAULT_MASKS, (EMAIL, CARD)):
        assert Masker(rules).mask(text) == ReferenceMasker(rules).mask(text)


@requires_native
@settings(max_examples=300, deadline=None)
@given(pieces=st.lists(PIECES, min_size=1, max_size=10), separator=st.sampled_from([" ", "  ", ", ", "; ", ""]))
def test_the_native_masker_class_matches_the_reference_on_random_lines(pieces: list[str], separator: str) -> None:
    rules = resolve_masks(["all"])
    text = separator.join(pieces)
    assert Masker(rules).mask(text) == ReferenceMasker(rules).mask(text)
