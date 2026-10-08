use std::path::PathBuf;

use logfold_core::{FrozenTemplate, MaskRule, MinerSnapshot};
use logfold_io::{FormatConfig, TimeWindow};

use crate::error::EngineError;

/// Default size of a chunk of the chunked strategy.
pub const DEFAULT_CHUNK_BYTES: u64 = 64 << 20;

/// Mining parameters (see `docs/ALGORITHM.md` §3 and §4).
#[derive(Clone, Debug)]
pub struct MiningConfig {
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

impl Default for MiningConfig {
    fn default() -> Self {
        MiningConfig {
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
pub enum ExecutionStrategy {
    /// One tree for the whole input.
    Sequential,
    /// Fixed-size chunks mined in parallel and merged in order.
    Chunked {
        /// Chunk size in bytes.
        chunk_bytes: u64,
        /// Worker thread count.
        threads: usize,
    },
    /// The chunked strategy, unless the first chunk shows that almost every record opens a new template; then one
    /// tree for the whole input, as with [`ExecutionStrategy::Sequential`].
    Adaptive {
        /// Chunk size in bytes.
        chunk_bytes: u64,
        /// Worker thread count.
        threads: usize,
    },
}

impl ExecutionStrategy {
    /// Builds a strategy from its name: `sequential`, `chunked` or `adaptive`.
    ///
    /// `chunk_bytes` defaults to [`DEFAULT_CHUNK_BYTES`] and `threads` to the available parallelism; the sequential
    /// strategy ignores both.
    pub fn from_name(name: &str, chunk_bytes: Option<u64>, threads: Option<usize>) -> Result<Self, EngineError> {
        let chunk_bytes = chunk_bytes.unwrap_or(DEFAULT_CHUNK_BYTES);
        let threads = threads.unwrap_or_else(|| std::thread::available_parallelism().map_or(1, |n| n.get()));
        match name {
            "sequential" => Ok(ExecutionStrategy::Sequential),
            "chunked" => Ok(ExecutionStrategy::Chunked { chunk_bytes, threads }),
            "adaptive" => Ok(ExecutionStrategy::Adaptive { chunk_bytes, threads }),
            other => Err(EngineError::Config(format!("unknown strategy '{other}'"))),
        }
    }
}

/// Everything needed to mine one or more runs.
#[derive(Clone, Debug)]
pub struct MineRequest {
    /// Runs, each an ordered list of input paths (`-` is standard input).
    pub runs: Vec<Vec<PathBuf>>,
    /// One time window per run, or empty for no windows: only records inside the window of their run are mined
    /// (see `docs/ALGORITHM.md` §8a).
    pub windows: Vec<TimeWindow>,
    /// Log format.
    pub format: FormatConfig,
    /// Masking rules, applied in order.
    pub masks: Vec<MaskRule>,
    /// Mining parameters.
    pub mining: MiningConfig,
    /// Execution strategy.
    pub strategy: ExecutionStrategy,
    /// Chunked mining only: train the first chunk alone and start every other chunk from a copy of its tree (see
    /// `docs/ALGORITHM.md` §6). Fewer stray templates, at the price of a serial prefix of one chunk.
    pub warm_start: bool,
    /// Re-assign every record to the finished tree after training (see `docs/ALGORITHM.md` §9). Gives a
    /// consistent assignment across runs and costs a second pass over the inputs.
    pub recount: bool,
    /// A saved miner to continue from: the new records are mined on top of its tree with empty statistics, and the
    /// counts of the earlier runs stay in its history. Only the sequential strategy continues a saved tree; the
    /// adaptive strategy then mines sequentially and the chunked one is refused.
    pub initial: Option<MinerSnapshot>,
    /// Return a snapshot of the trained miner in [`MineOutput::snapshot`].
    pub keep_snapshot: bool,
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
    /// Records left out because their timestamp is outside the time window.
    pub out_of_range: u64,
    /// Records left out because they have no timestamp and the time window has a bound.
    pub untimed: u64,
    /// Total size of the inputs on disk.
    pub bytes: u64,
    /// True when any timestamp carried a zone.
    pub tz_aware: bool,
    /// True when records fell into overflow clusters.
    pub overflowed: bool,
}

/// Timings and execution facts.
#[derive(Clone, Debug)]
pub struct RunMetrics {
    /// `sequential` or `chunked`: the strategy that mined the input (an adaptive request reports what it chose).
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
    /// Unique templates sorted by total count. When the request continues a saved miner, templates with no record in
    /// these runs are left out.
    pub templates: Vec<FrozenTemplate>,
    /// The trained miner, when the request asked for it.
    pub snapshot: Option<MinerSnapshot>,
    /// Set by [`crate::match_records`]: for every run, the records that matched no template as pairs `(token count,
    /// records)` sorted by token count. `None` when the run was trained.
    pub unmatched: Option<Vec<Vec<(usize, u64)>>>,
    /// Timings.
    pub metrics: RunMetrics,
}

/// Receives progress and can cancel a run. Called from worker threads.
pub trait ProgressObserver: Sync {
    /// Called with the number of input bytes consumed since the previous call.
    fn on_bytes(&self, _consumed: u64) {}

    /// Returns true when the run should stop.
    fn cancelled(&self) -> bool {
        false
    }
}

/// ProgressObserver that ignores everything.
pub struct NullObserver;

impl ProgressObserver for NullObserver {}
