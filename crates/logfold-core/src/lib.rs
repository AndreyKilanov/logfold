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
mod mask_check;
mod masker;
mod miner;
mod parameters;
mod stats;
mod tokenizer;
mod values;

pub use compare::{
    Changed, Comparison, MIN_WORDS, Matcher, Side, Thresholds, compare_runs, jaccard_idf_pairs, jaccard_pairs,
    overlap_pairs, rules_pairs, token_subset_pairs,
};
pub use error::CoreError;
pub use freeze::{FrozenTemplate, model_templates, template_id};
pub use level::{LEVEL_COUNT, Level};
pub use mask_check::MaskCheck;
pub use masker::{MAX_MASK_RULES, MAX_PATTERN_BYTES, MaskHit, MaskRule, MaskScratch, RuleMasker, default_mask_rules};
pub use miner::{
    Assignment, ClusterHistory, ClusterSnapshot, DrainMiner, MAX_EXAMPLE_BYTES, MatchRule, MinerConfig, MinerSnapshot,
    NodeSnapshot, OnFull, RecordMeta, Recount, WILDCARD,
};
pub use parameters::{Fit, Parameter, WILDCARD_NAME, extract_parameters};
pub use stats::RunStats;
pub use tokenizer::{TokenView, Tokenizer};
pub use values::{
    Distribution, MAX_DISTINCT, MAX_VALUE_BYTES, NumericSummary, Slot, TOP_VALUES, ValueCollector, ValueSummary,
};

/// Version of the algorithm contract in `docs/ALGORITHM.md`.
pub const ALGO_VERSION: u32 = 1;
