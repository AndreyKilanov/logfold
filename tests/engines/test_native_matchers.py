"""The matchers give exactly the pairs of the quadratic oracles of ``tests/oracles.py``."""

from __future__ import annotations

import math
import random
import time

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import requires_native
from logfold import _bridge as native
from logfold.comparison import TokenSubsetMatcher
from logfold.errors import ConfigError
from logfold.plugins.matchers import JaccardMatcher
from oracles import quadratic_jaccard, quadratic_token_subset

pytestmark = requires_native

TOKENS = st.sampled_from(["a", "b", "c", "<*>", "<*>", "", "é", "<NUM>", "x" * 40, "\x1c", chr(0xA0), chr(0x2003)])
TEMPLATES = st.lists(TOKENS, max_size=6).map(" ".join)
TEMPLATE_LISTS = st.lists(TEMPLATES, max_size=40)
THRESHOLDS = st.sampled_from([0.0, 0.1, 0.3, 0.5, 0.6, 2 / 3, 0.75, 0.9, 1.0, 1.5])


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS)
def test_token_subset_equals_the_oracle(before: list[str], after: list[str]) -> None:
    assert native.match_templates("token_subset", before, after) == TokenSubsetMatcher().match(before, after)
    assert native.match_templates("token_subset", before, after) == quadratic_token_subset(before, after)


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS, threshold=THRESHOLDS)
def test_jaccard_equals_the_oracle(before: list[str], after: list[str], threshold: float) -> None:
    matcher = JaccardMatcher()
    matcher.threshold = threshold
    expected = quadratic_jaccard(before, after, threshold)
    assert native.match_templates("jaccard", before, after, threshold) == expected
    assert matcher.match(before, after) == expected


def test_unknown_matchers_and_missing_threshold_are_config_errors() -> None:
    with pytest.raises(ConfigError, match="unknown matcher"):
        native.match_templates("nope", ["a"], ["a"])
    with pytest.raises(ConfigError, match="threshold"):
        native.match_templates("jaccard", ["a"], ["a"])


def test_a_subclass_keeps_the_threshold_of_its_class() -> None:
    class Strict(JaccardMatcher):
        name = "strict"
        threshold = 1.0

    before, after = ["a b c d"], ["a b c e"]
    assert Strict().match(before, after) == []
    assert JaccardMatcher().match(before, after) == [(0, 0)]


def test_a_threshold_nobody_can_reach_pairs_nothing_and_zero_or_less_pairs_everything() -> None:
    before, after = ["a b c d", "x y"], ["a b c e", "p q"]
    for threshold in (math.nan, math.inf, 1.5):
        assert native.match_templates("jaccard", before, after, threshold) == []
    for threshold in (0.0, -1.0, -math.inf):
        assert native.match_templates("jaccard", before, after, threshold) == quadratic_jaccard(before, after, 0.0)
        assert len(native.match_templates("jaccard", before, after, threshold)) == 2


def test_lone_surrogates_are_read_as_the_replacement_character() -> None:
    before, after = ["user \ud800 failed", "disk full"], ["user <*> failed", "disk full"]
    assert native.match_templates("token_subset", before, after) == [(0, 0), (1, 1)]
    assert TokenSubsetMatcher().match(before, after) == [(0, 0), (1, 1)]
    assert native.match_templates("jaccard", ["a \udc80 b"], ["a \ud800 b"], 0.9) == [(0, 0)]


def sparse(rng: random.Random, count: int) -> list[str]:
    words = [f"w{i}" for i in range(3000)]
    return [
        " ".join(["INFO", f"svc{rng.randrange(count // 4)}", *(rng.choice(words) for _ in range(rng.randrange(3, 9)))])
        for _ in range(count)
    ]


def test_the_native_matchers_handle_a_hundred_thousand_templates() -> None:
    rng = random.Random(21)
    before, after = sparse(rng, 100_000), sparse(rng, 100_000)
    started = time.perf_counter()
    native.match_templates("token_subset", before, after)
    native.match_templates("jaccard", before, after, 0.6)
    elapsed = time.perf_counter() - started
    assert elapsed < 30.0, f"{elapsed:.1f}s for both matchers on 100 thousand templates"


def test_unusual_jaccard_thresholds_are_read_as_the_contract_says() -> None:
    for threshold in (0.0, -1.0, float("nan"), float("inf")):
        matcher = JaccardMatcher()
        matcher.threshold = threshold
        expected = [] if threshold != threshold or threshold > 1 else [(0, 0)]
        assert matcher.match(["a b"], ["a b"]) == expected
