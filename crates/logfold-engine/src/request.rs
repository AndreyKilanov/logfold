use std::path::PathBuf;

use logfold_core::{FrozenTemplate, MaskRule};
use logfold_io::FormatConfig;

/// Default size of a chunk of the chunked strategy.
pub const DEFAULT_CHUNK_BYTES: u64 = 64 << 20;

/// Mining parameters (see `docs/ALGORITHM.md` §3 and §4).
#[derive(Clone, Debug)]
pub struct MiningParams {
    /// Tree depth, at least 3.
    pub depth: usize,
    /// Similarity threshold in `[0, 1]`.
    pub sim_th: f64,
    /// Maximum children per tree node.
    pub max_children: usize,
    /// Maximum number of clusters before records go to overflow clusters.
    pub max_templates: usize,
    /// ASCII delimiter bytes.
    pub delimiters: Vec<u8>,
}

impl Default for MiningParams {
    fn default() -> Self {
        MiningParams {
            depth: 4,
            sim_th: 0.4,
            max_children: 100,
            max_templates: 100_000,
            delimiters: b" \t\n\r".to_vec(),
        }
    }
}

/// How the work is executed.
#[derive(Clone, Copy, Debug)]
pub enum Strategy {
    /// One tree for the whole input.
    Sequential,
    /// Fixed-size chunks mined in parallel and merged in order.
    Chunked {
        /// Chunk size in bytes.
        chunk_bytes: u64,
        /// Worker thread count.
        threads: usize,
    },
}

/// Everything needed to mine one or more runs.
#[derive(Clone, Debug)]
pub struct MineRequest {
    /// Runs, each an ordered list of input paths (`-` is standard input).
    pub runs: Vec<Vec<PathBuf>>,
    /// Log format.
    pub format: FormatConfig,
    /// Masking rules, applied in order.
    pub masks: Vec<MaskRule>,
    /// Mining parameters.
    pub mining: MiningParams,
    /// Execution strategy.
    pub strategy: Strategy,
    /// Re-assign every record to the finished tree after training (see `docs/ALGORITHM.md` §9). Gives a
    /// consistent assignment across runs and costs a second pass over the inputs.
    pub recount: bool,
}

/// Counters of one run.
#[derive(Clone, Debug)]
pub struct RunSummary {
    /// Number of input files.
    pub files: usize,
    /// Non-skipped physical lines.
    pub lines: u64,
    /// Parsed records.
    pub records: u64,
    /// Lines that did not become part of a record.
    pub unparsed: u64,
    /// Total size of the inputs on disk.
    pub bytes: u64,
    /// True when any timestamp carried a zone.
    pub tz_aware: bool,
    /// True when records fell into overflow clusters.
    pub overflowed: bool,
}

/// Timings and execution facts.
#[derive(Clone, Debug)]
pub struct Metrics {
    /// `sequential` or `chunked`.
    pub strategy: &'static str,
    /// Worker threads used.
    pub threads: usize,
    /// Number of planned chunks.
    pub chunks: usize,
    /// Wall time of the whole call.
    pub wall_total_s: f64,
    /// Wall time of reading, parsing and mining (including merging).
    pub wall_mine_s: f64,
    /// Time spent merging chunk trees on the merging thread.
    pub wall_merge_s: f64,
    /// Time spent re-assigning records to the finished tree (0 without recount).
    pub wall_recount_s: f64,
    /// Time spent freezing the result.
    pub wall_freeze_s: f64,
}

/// Result of [`crate::mine`].
#[derive(Debug)]
pub struct MineOutput {
    /// Per-run counters.
    pub runs: Vec<RunSummary>,
    /// Unique templates sorted by total count.
    pub templates: Vec<FrozenTemplate>,
    /// Timings.
    pub metrics: Metrics,
}

/// Receives progress and can cancel a run. Called from worker threads.
pub trait Observer: Sync {
    /// Called with the number of input bytes consumed since the previous call.
    fn on_bytes(&self, _consumed: u64) {}

    /// Returns true when the run should stop.
    fn cancelled(&self) -> bool {
        false
    }
}

/// Observer that ignores everything.
pub struct NoObserver;

impl Observer for NoObserver {}
