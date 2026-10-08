"""The native jaccard-idf, overlap and rules matchers give exactly the pairs of the Python reference."""

from __future__ import annotations

import random
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import requires_native
from logfold import _bridge as native
from logfold.api.matching import accelerated, native_spec
from logfold.plugins.matchers import JaccardIdfMatcher, OverlapMatcher, RulesMatcher
from oracles import quadratic_jaccard_idf, quadratic_overlap

pytestmark = requires_native

TOKENS = st.sampled_from(["a", "b", "c", "d", "<*>", "<*>", "", "é", "<NUM>", "x" * 40, "\x1c", chr(0xA0), chr(0x2003)])
TEMPLATES = st.lists(TOKENS, max_size=7).map(" ".join)
TEMPLATE_LISTS = st.lists(TEMPLATES, max_size=40)
THRESHOLDS = st.sampled_from([0.0, 0.1, 0.3, 0.5, 0.6, 2 / 3, 0.75, 0.8, 0.9, 1.0, 1.5])
RULES = st.lists(st.tuples(TEMPLATES, TEMPLATES), max_size=6)
SETTINGS = settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])


@SETTINGS
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS, threshold=THRESHOLDS)
def test_native_jaccard_idf_equals_python_and_the_oracle(before: list[str], after: list[str], threshold: float) -> None:
    matcher = JaccardIdfMatcher()
    matcher.threshold = threshold
    expected = quadratic_jaccard_idf(before, after, threshold)
    assert native.match_templates("jaccard_idf", before, after, threshold) == expected
    assert matcher.match(before, after) == expected


@SETTINGS
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS, threshold=THRESHOLDS)
def test_native_overlap_equals_python_and_the_oracle(before: list[str], after: list[str], threshold: float) -> None:
    matcher = OverlapMatcher()
    matcher.threshold = threshold
    expected = quadratic_overlap(before, after, threshold)
    assert native.match_templates("overlap", before, after, threshold) == expected
    assert matcher.match(before, after) == expected


@SETTINGS
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS, rules=RULES)
def test_native_rules_equal_python(before: list[str], after: list[str], rules: list[tuple[str, str]]) -> None:
    assert native.match_templates("rules", before, after, None, rules) == RulesMatcher(rules).match(before, after)


def test_overlap_catches_an_extended_message_that_jaccard_misses() -> None:
    before = ["cache cleared for tenant <NUM>"]
    after = ["cache cleared for tenant <NUM> after a restart of the node"]
    assert OverlapMatcher().match(before, after) == [(0, 0)]
    assert native.match_templates("overlap", before, after, 0.8) == [(0, 0)]


def test_overlap_never_pairs_a_template_of_fewer_than_three_words() -> None:
    assert OverlapMatcher().match(["cache cleared"], ["cache cleared now for the tenant"]) == []
    assert native.match_templates("overlap", ["cache cleared"], ["cache cleared now for the tenant"], 0.8) == []


def test_jaccard_idf_separates_siblings_that_differ_in_their_rare_word() -> None:
    before = ["connection to db1 lost after <NUM> retries", "connection to db2 lost after <NUM> retries"]
    after = ["connection to db2 closed after <NUM> retries", "connection to db1 closed after <NUM> retries"]
    expected = [(0, 1), (1, 0)]
    assert JaccardIdfMatcher().match(before, after) == expected
    assert native.match_templates("jaccard_idf", before, after, 0.5) == expected


def test_rules_pair_the_listed_messages_in_both_directions() -> None:
    rules = [("retry failed after <NUM> attempts", "retry gave up after <NUM> attempts")]
    before = ["retry failed after <NUM> attempts", "disk full"]
    after = ["disk full now", "retry gave up after <NUM> attempts"]
    assert RulesMatcher(rules).match(before, after) == [(0, 1)]
    assert native.match_templates("rules", before, after, None, rules) == [(0, 1)]
    swapped = [("retry gave up after <NUM> attempts", "retry failed after <NUM> attempts")]
    assert native.match_templates("rules", before, after, None, swapped) == [(0, 1)]


def test_rules_wildcards_agree_with_any_token_on_both_sides() -> None:
    rules = [("retry <*> after <NUM> attempts", "gave up")]
    assert native.match_templates("rules", ["retry failed after <NUM> attempts"], ["gave up"], None, rules) == [(0, 0)]
    assert native.match_templates("rules", ["retry <*> after <NUM> attempts"], ["gave <*>"], None, rules) == [(0, 0)]
    assert native.match_templates("rules", ["retry failed after <NUM> attempts"], ["gave"], None, rules) == []


def test_every_template_is_used_once_in_the_order_of_the_rules() -> None:
    rules = [("a b", "c d"), ("a b", "e f")]
    before = ["a b"]
    after = ["c d", "e f"]
    assert native.match_templates("rules", before, after, None, rules) == [(0, 0)]


def test_the_new_matchers_are_accelerated_with_the_threshold_and_the_rules_of_the_instance() -> None:
    for matcher in (JaccardIdfMatcher(), OverlapMatcher()):
        assert accelerated(matcher).__class__.__name__ == "_NativeMatcher"
        assert native_spec(matcher) is not None
    rules = RulesMatcher([("a", "b")])
    assert native_spec(rules) == ("rules", None, (("a", "b"),))
    assert native_spec(RulesMatcher()) is None
    strict = JaccardIdfMatcher()
    strict.threshold = float("nan")
    assert accelerated(strict) is strict


def test_missing_threshold_and_rules_are_config_errors() -> None:
    for kind in ("jaccard_idf", "overlap"):
        with pytest.raises(native.ConfigError, match="threshold"):
            native.match_templates(kind, ["a"], ["a"])
    with pytest.raises(native.ConfigError, match="rules"):
        native.match_templates("rules", ["a"], ["a"])


def sparse(rng: random.Random, count: int) -> list[str]:
    words = [f"w{i}" for i in range(3000)]
    return [
        " ".join(["INFO", f"svc{rng.randrange(count // 4)}", *(rng.choice(words) for _ in range(rng.randrange(3, 9)))])
        for _ in range(count)
    ]


def test_the_new_matchers_handle_a_hundred_thousand_templates() -> None:
    rng = random.Random(22)
    before, after = sparse(rng, 100_000), sparse(rng, 100_000)
    rules = [(before[i], after[i]) for i in range(0, 100_000, 50)]
    started = time.perf_counter()
    native.match_templates("jaccard_idf", before, after, 0.5)
    native.match_templates("overlap", before, after, 0.8)
    native.match_templates("rules", before, after, None, rules)
    elapsed = time.perf_counter() - started
    assert elapsed < 30.0, f"{elapsed:.1f}s for the three matchers on 100 thousand templates"
