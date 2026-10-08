//! Pure domain core of logfold.
//!
//! This crate contains no file I/O, threads, serialization formats or Python bindings. It implements the algorithm
//! described in `docs/ALGORITHM.md`: masking, tokenization, the Drain-compatible template tree, ordered merge and
//! freezing of the result, and the pairing of templates that exist in one run only.

#![forbid(unsafe_code)]

mod compare;
mod default_masks;
mod error;
mod freeze;
mod level;
mod masker;
mod miner;
pub mod report;
mod stats;
mod tokenizer;

pub use compare::{
    Changed, Comparison, MIN_WORDS, Matcher, Side, Thresholds, compare_runs, jaccard_idf_pairs, jaccard_pairs,
    overlap_pairs, rules_pairs, token_subset_pairs,
};
pub use error::CoreError;
pub use freeze::FrozenTemplate;
pub use level::{LEVEL_COUNT, Level};
pub use masker::{MaskRule, MaskScratch, RuleMasker, default_mask_rules};
pub use miner::{
    Assigned, ClusterSnapshot, DrainMiner, History, MAX_EXAMPLE_BYTES, MinerConfig, MinerSnapshot, NodeSnapshot,
    RecordMeta, Recount, WILDCARD,
};
pub use stats::RunStats;
pub use tokenizer::{TokenView, Tokenizer};

/// Version of the algorithm contract in `docs/ALGORITHM.md`.
pub const ALGO_VERSION: u32 = 1;
