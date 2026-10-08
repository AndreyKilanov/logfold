"""The native matchers give exactly the pairs of the pure-Python reference matchers."""

from __future__ import annotations

import random
import time
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import logfold
from conftest import requires_native
from corpora import synthetic_pair
from logfold import _bridge as native
from logfold.api.matching import accelerated
from logfold.comparison import ExactMatcher, TokenSubsetMatcher
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
def test_native_token_subset_equals_python(before: list[str], after: list[str]) -> None:
    assert native.match_templates("token_subset", before, after) == TokenSubsetMatcher().match(before, after)
    assert native.match_templates("token_subset", before, after) == quadratic_token_subset(before, after)


@settings(max_examples=500, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS, threshold=THRESHOLDS)
def test_native_jaccard_equals_python(before: list[str], after: list[str], threshold: float) -> None:
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


def test_only_the_built_in_matchers_are_accelerated() -> None:
    assert accelerated(TokenSubsetMatcher()).__class__.__name__ == "_NativeMatcher"
    assert accelerated(JaccardMatcher()).__class__.__name__ == "_NativeMatcher"
    exact = ExactMatcher()
    assert accelerated(exact) is exact

    class Custom(TokenSubsetMatcher):
        name = "custom"

    custom = Custom()
    assert accelerated(custom) is custom
    plain = TokenSubsetMatcher()
    assert accelerated(plain, enabled=False) is plain


def test_accelerated_jaccard_keeps_the_threshold_of_the_instance() -> None:
    class Strict(JaccardMatcher):
        name = "strict"
        threshold = 1.0

    before, after = ["a b c d"], ["a b c e"]
    assert Strict().match(before, after) == []
    assert JaccardMatcher().match(before, after) == [(0, 0)]
    assert accelerated(JaccardMatcher()).match(before, after) == [(0, 0)]


def test_lone_surrogates_fall_back_to_the_python_matcher() -> None:
    before, after = ["user \ud800 failed", "disk full"], ["user <*> failed", "disk full"]
    with pytest.raises(UnicodeError):
        native.match_templates("token_subset", before, after)
    expected = TokenSubsetMatcher().match(before, after)
    assert accelerated(TokenSubsetMatcher()).match(before, after) == expected == [(0, 0), (1, 1)]


@pytest.mark.parametrize("matcher", ["token_subset", "jaccard"])
def test_diff_is_identical_with_and_without_the_native_matchers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, matcher: str
) -> None:
    before, after, _truth = synthetic_pair(tmp_path, 5)
    first = logfold.analyze(str(before), format="app")
    second = logfold.analyze(str(after), format="app")
    fast = logfold.diff(first, second, matcher=matcher, min_count=0)
    monkeypatch.setattr(native, "supports_matching", lambda: False)
    slow = logfold.diff(first, second, matcher=matcher, min_count=0)
    assert fast.new_templates == slow.new_templates
    assert fast.disappeared == slow.disappeared
    assert fast.changed == slow.changed
    assert fast.unchanged == slow.unchanged


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


def test_unusual_jaccard_thresholds_keep_the_python_matcher() -> None:
    for threshold in (0.0, -1.0, float("nan"), float("inf")):
        matcher = JaccardMatcher()
        matcher.threshold = threshold
        assert accelerated(matcher) is matcher
        expected = [] if threshold != threshold or threshold > 1 else [(0, 0)]
        assert matcher.match(["a b"], ["a b"]) == expected
