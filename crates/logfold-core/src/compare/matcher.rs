//! The matchers that pair the templates existing in one run only, and their names.

use crate::error::CoreError;

use super::{jaccard_idf_pairs, jaccard_pairs, overlap_pairs, rules_pairs, token_subset_pairs};

/// The matcher that pairs the templates that exist in one run only.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Matcher<'a> {
    /// Pairs nothing: a template is the same only when its text is the same.
    Exact,
    /// See [`token_subset_pairs`].
    TokenSubset,
    /// See [`jaccard_pairs`], with this threshold.
    Jaccard(f64),
    /// See [`jaccard_idf_pairs`], with this threshold.
    JaccardIdf(f64),
    /// See [`overlap_pairs`], with this threshold.
    Overlap(f64),
    /// See [`rules_pairs`], with these rules.
    Rules(&'a [(&'a str, &'a str)]),
}

impl<'a> Matcher<'a> {
    /// Builds a matcher from its name: `exact`, `token_subset`, `jaccard`, `jaccard_idf`, `overlap` or `rules`.
    ///
    /// `jaccard`, `jaccard_idf` and `overlap` need a `threshold`, `rules` needs `rules`; both are ignored by the other
    /// matchers.
    pub fn from_name(
        name: &str,
        threshold: Option<f64>,
        rules: Option<&'a [(&'a str, &'a str)]>,
    ) -> Result<Self, CoreError> {
        let need =
            || threshold.ok_or_else(|| CoreError::InvalidConfig(format!("the {name} matcher needs a threshold")));
        match name {
            "exact" => Ok(Matcher::Exact),
            "token_subset" => Ok(Matcher::TokenSubset),
            "jaccard" => Ok(Matcher::Jaccard(need()?)),
            "jaccard_idf" => Ok(Matcher::JaccardIdf(need()?)),
            "overlap" => Ok(Matcher::Overlap(need()?)),
            "rules" => rules
                .map(Matcher::Rules)
                .ok_or_else(|| CoreError::InvalidConfig("the rules matcher needs rules".into())),
            other => Err(CoreError::InvalidConfig(format!("unknown matcher {other:?}"))),
        }
    }

    /// Pairs the templates of `before` with those of `after`: `(before index, after index)`, each index at most once.
    pub fn pairs(&self, before: &[&str], after: &[&str]) -> Vec<(usize, usize)> {
        match *self {
            Matcher::Exact => Vec::new(),
            Matcher::TokenSubset => token_subset_pairs(before, after),
            Matcher::Jaccard(threshold) => jaccard_pairs(before, after, threshold),
            Matcher::JaccardIdf(threshold) => jaccard_idf_pairs(before, after, threshold),
            Matcher::Overlap(threshold) => overlap_pairs(before, after, threshold),
            Matcher::Rules(rules) => rules_pairs(before, after, rules),
        }
    }
}
