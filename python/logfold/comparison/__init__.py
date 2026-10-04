"""Comparison policy: classification of two runs and the built-in matchers."""

from __future__ import annotations

from logfold.comparison.classify import Classification, classify
from logfold.comparison.matchers import ExactMatcher, TokenSubsetMatcher
from logfold.ext.registry import register_matcher

register_matcher(ExactMatcher())
register_matcher(TokenSubsetMatcher())

__all__ = ["Classification", "ExactMatcher", "TokenSubsetMatcher", "classify"]
