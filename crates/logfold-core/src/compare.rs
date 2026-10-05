//! Pairing of templates that exist in one run only (`docs/ALGORITHM.md` §10).
//!
//! The miner puts templates of both runs into one tree, so a template present in both runs is the same template. A
//! matcher handles the rest: it receives the texts of the templates of a single run and returns index pairs that
//! describe the same event. Both matchers here are exact re-implementations of the pure-Python reference matchers, and
//! both avoid comparing every pair of templates.

mod jaccard;
mod token_subset;

pub use jaccard::jaccard_pairs;
pub use token_subset::token_subset_pairs;
