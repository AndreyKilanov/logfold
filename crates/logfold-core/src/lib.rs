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
mod stats;
mod tokenizer;

pub use compare::{compare_runs, jaccard_pairs, token_subset_pairs, Changed, Comparison, Matcher, Side, Thresholds};
pub use error::CoreError;
pub use freeze::FrozenTemplate;
pub use level::{Level, LEVEL_COUNT};
pub use masker::{default_mask_rules, MaskRule, MaskScratch, RuleMasker};
pub use miner::{Assigned, DrainMiner, MinerConfig, RecordMeta, Recount, MAX_EXAMPLE_BYTES, WILDCARD};
pub use stats::RunStats;
pub use tokenizer::{TokenView, Tokenizer};

/// Version of the algorithm contract in `docs/ALGORITHM.md`.
pub const ALGO_VERSION: u32 = 1;
