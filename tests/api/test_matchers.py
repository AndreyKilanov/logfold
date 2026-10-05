"""The indexed ``token_subset`` and ``jaccard`` matchers give exactly the pairs of the original quadratic searches."""

from __future__ import annotations

import math
import random
import time

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from logfold.comparison import TokenSubsetMatcher
from logfold.comparison.matchers import _generalizes
from logfold.plugins.matchers import JaccardMatcher
from oracles import quadratic_jaccard, quadratic_token_subset

TOKENS = st.sampled_from(["a", "b", "c", "<*>", "<*>", "", "é", "<NUM>", "x" * 40])
TEMPLATES = st.lists(TOKENS, max_size=6).map(" ".join)
TEMPLATE_LISTS = st.lists(TEMPLATES, max_size=40)


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS)
def test_indexed_matcher_equals_the_quadratic_search(before: list[str], after: list[str]) -> None:
    assert TokenSubsetMatcher().match(before, after) == quadratic_token_subset(before, after)


@settings(max_examples=200, deadline=None)
@given(before=TEMPLATE_LISTS, after=TEMPLATE_LISTS)
def test_every_index_is_used_once_and_every_pair_generalizes(before: list[str], after: list[str]) -> None:
    pairs = TokenSubsetMatcher().match(before, after)
    assert len({i for i, _ in pairs}) == len(pairs)
    assert len({j for _, j in pairs}) == len(pairs)
    for i, j in pairs:
        left = before[i].split(" ") if before[i] else []
        right = after[j].split(" ") if after[j] else []
        assert _generalizes(left, right) or _generalizes(right, left)


def test_ties_go_to_the_fewest_wildcard_differences_then_the_lowest_index() -> None:
    before = ["user <*> failed", "user <*> <*>", "user bob failed", "user bob failed"]
    after = ["user bob failed"]
    assert TokenSubsetMatcher().match(before, after) == [(2, 0)]
    assert TokenSubsetMatcher().match(["a <*>", "a <*>"], ["a b"]) == [(0, 0)]


def test_empty_inputs_and_empty_templates() -> None:
    matcher = TokenSubsetMatcher()
    assert matcher.match([], []) == []
    assert matcher.match(["a"], []) == []
    assert matcher.match([], ["a"]) == []
    assert matcher.match(["", ""], ["", ""]) == [(0, 0), (1, 1)]


def crowded(rng: random.Random, count: int) -> list[str]:
    """Templates of one length with a few literal tokens shared by many and one rare token."""
    templates = []
    for _ in range(count):
        tokens = ["INFO", f"svc{rng.randrange(count // 2 + 1)}", rng.choice(["start", "stop", "<*>"])]
        tokens += [rng.choice(["x", "y", "<*>"]) for _ in range(3)] + [f"op{rng.randrange(900)}"]
        templates.append(" ".join(tokens))
    return templates


def test_indexed_matcher_equals_the_quadratic_search_on_crowded_templates() -> None:
    rng = random.Random(7)
    before, after = crowded(rng, 600), crowded(rng, 600)
    assert TokenSubsetMatcher().match(before, after) == quadratic_token_subset(before, after)


def test_twenty_thousand_templates_do_not_take_quadratic_time() -> None:
    rng = random.Random(11)
    before, after = crowded(rng, 20_000), crowded(rng, 20_000)
    started = time.perf_counter()
    pairs = TokenSubsetMatcher().match(before, after)
    elapsed = time.perf_counter() - started
    assert pairs
    assert elapsed < 20.0, f"{elapsed:.1f}s; the quadratic search needs minutes on this input"


def jaccard_with(threshold: float) -> JaccardMatcher:
    matcher = JaccardMatcher()
    matcher.threshold = threshold
    return matcher


WORDS = st.sampled_from(["a", "b", "c", "d", "e", "<*>", "<NUM>", "é", "user", "failed", "x" * 30])
SENTENCES = st.lists(WORDS, max_size=8).map(" ".join)
SENTENCE_LISTS = st.lists(SENTENCES, max_size=30)
THRESHOLDS = st.sampled_from([0.0, -1.0, 0.1, 0.3, 0.5, 0.6, 2 / 3, 0.75, 0.9, 1.0, 1.5, math.inf, math.nan])


@settings(max_examples=400, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(before=SENTENCE_LISTS, after=SENTENCE_LISTS, threshold=THRESHOLDS)
def test_prefix_filtered_jaccard_equals_the_quadratic_search(
    before: list[str], after: list[str], threshold: float
) -> None:
    assert jaccard_with(threshold).match(before, after) == quadratic_jaccard(before, after, threshold)


def test_jaccard_equals_the_quadratic_search_on_crowded_templates() -> None:
    rng = random.Random(5)
    before, after = crowded(rng, 500), crowded(rng, 500)
    for threshold in (0.4, 0.6, 0.8):
        assert jaccard_with(threshold).match(before, after) == quadratic_jaccard(before, after, threshold)


def sparse(rng: random.Random, count: int) -> list[str]:
    """Templates like those of real logs: a few fixed words and several words from a large vocabulary."""
    words = [f"w{i}" for i in range(3000)]
    return [
        " ".join(["INFO", f"svc{rng.randrange(count // 4)}", *(rng.choice(words) for _ in range(rng.randrange(3, 9)))])
        for _ in range(count)
    ]


def test_twenty_thousand_templates_do_not_take_quadratic_time_for_jaccard() -> None:
    rng = random.Random(13)
    before, after = sparse(rng, 20_000), sparse(rng, 20_000)
    started = time.perf_counter()
    JaccardMatcher().match(before, after)
    elapsed = time.perf_counter() - started
    assert elapsed < 20.0, f"{elapsed:.1f}s; the quadratic search needs minutes on this input"
