//! Pairing of templates that exist in one run only (`docs/ALGORITHM.md` §10) and the classification of the templates
//! of two runs (§11).
//!
//! The miner puts templates of both runs into one tree, so a template present in both runs is the same template. A
//! matcher handles the rest: it receives the texts of the templates of a single run and returns index pairs that
//! describe the same event. The matchers here are exact re-implementations of the pure-Python reference matchers, and
//! the ones that score pairs avoid comparing every pair of templates.

mod classify;
mod jaccard;
mod jaccard_idf;
mod overlap;
mod rules;
mod sets;
mod token_subset;

pub use classify::{Changed, Comparison, Matcher, Side, Thresholds, compare_runs};
pub use jaccard::jaccard_pairs;
pub use jaccard_idf::jaccard_idf_pairs;
pub use overlap::{MIN_WORDS, overlap_pairs};
pub use rules::rules_pairs;
pub use token_subset::token_subset_pairs;
