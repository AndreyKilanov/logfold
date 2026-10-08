from __future__ import annotations

import pytest

from logfold import ConfigError, MaskRule
from logfold.config import DEFAULT_MASKS
from logfold.ext.masks import Masker, validate_masks


def masked(text: str, rules: tuple[MaskRule, ...] = DEFAULT_MASKS) -> str:
    return Masker(rules).mask(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("conn from 10.0.0.1:8080 took 12.5 ms", "conn from <IP> took <NUM> ms"),
        ("id 123e4567-e89b-12d3-a456-426614174000 ok", "id <UUID> ok"),
        ("at 2026-10-04 12:00:01.123Z done", "at <TS> done"),
        ("at 2026-10-04T12:00:01+02:00 done", "at <TS> done"),
        ("open /var/log/app.log", "open <PATH>"),
        ("ptr 0xdeadBEEF", "ptr <HEX>"),
        ("user42 failed", "user42 failed"),
        ("a -5 b", "a -<NUM> b"),
        ("x+5", "x<NUM>"),
        ("1.5abc", "<NUM>.5abc"),
        ("1.2.3.4567", "<NUM>.<NUM>"),
        ("http://host/a/b?q=1", "http:/<PATH>?q=<NUM>"),
    ],
)
def test_default_rules(text: str, expected: str) -> None:
    assert masked(text) == expected


def test_earliest_rule_wins_at_the_same_position() -> None:
    rules = (MaskRule("a", "ab", "<A>", True), MaskRule("b", "abc", "<B>", True))
    assert masked("xabcx", rules) == "x<A>cx"


def test_leftmost_match_wins_over_rule_order() -> None:
    rules = (MaskRule("late", "cd", "<L>", True), MaskRule("early", "bc", "<E>", True))
    assert masked("abcd", rules) == "a<E>d"


def test_no_rules_is_the_identity() -> None:
    assert masked("keep 12", ()) == "keep 12"


def test_tokens_are_inserted_literally() -> None:
    assert masked("v1", (MaskRule("v", r"v\d", r"\1<X>\g<0>", True),)) == r"\1<X>\g<0>"


def test_invalid_rules_are_rejected() -> None:
    with pytest.raises(ConfigError):
        validate_masks([MaskRule("bad", "(", "<B>")])
    with pytest.raises(ConfigError):
        validate_masks([MaskRule("empty", "x*", "<E>")])


NATIVE_SAMPLES = [
    "conn from 10.0.0.1:8080 took 12.5 ms",
    "id 123e4567-e89b-12d3-a456-426614174000 ok",
    "at 2026-10-04 12:00:01.123Z done",
    "open /var/log/app.log and /tmp/x/y",
    "ptr 0xdeadBEEF and 0X1f",
    "a -5 b +7 c x+5 y-6",
    "1.5abc 1.2.3.4567 255.255.255.255:80x",
    "http://host/a/b?q=1&r=2.50",
    "2026-10-04T12:00:00+0200 2026-10-04T12:00:00+02:00 2026-10-04T12:00:00.5",
]


@pytest.mark.parametrize("text", NATIVE_SAMPLES)
def test_native_masking_matches_the_python_masker(text: str, tmp_path: pytest.TempPathFactory) -> None:
    import logfold
    from logfold import _bridge as native

    if not native.is_available():
        pytest.skip("native extension is not built")
    path = tmp_path / "one.log"  # type: ignore[operator]
    path.write_text(text + "\n", encoding="utf-8")
    result = logfold.analyze(str(path), format="plain", engine="native", strategy="sequential")
    assert result.templates[0].text == " ".join(masked(text).split())
