//! Application layer of logfold: the mining pipeline and its execution strategies.
//!
//! [`mine`] is the single entry point. It plans the work, runs it with the requested [`ExecutionStrategy`] and returns the
//! frozen templates together with per-run counters. Parallelism is deterministic: for a fixed chunk size the result
//! does not depend on the number of threads.

#![forbid(unsafe_code)]

mod adaptive;
mod checking;
mod chunked;
mod error;
mod inspect;
mod matching;
mod pipeline;
mod plan;
mod sequential;
mod session;
mod types;

use std::time::Instant;

pub use checking::check_records;
pub use error::EngineError;
pub use inspect::{SampleRecord, SampleReport, inspect_sample};
pub use logfold_core::{MatchRule, OnFull};
pub use matching::{match_records, match_records_with};
pub use session::{Session, SessionConfig};
pub use types::{
    CheckOutput, DEFAULT_CHUNK_BYTES, ExecutionStrategy, MatchBatch, MatchedTemplate, MineOutput, MineRequest,
    MiningConfig, NullObserver, ProgressObserver, RunMetrics, RunSummary,
};

use logfold_core::{CoreError, DrainMiner, MinerConfig, MinerSnapshot};
use logfold_io::StateError;
use pipeline::PipelineContext;

/// Memory that the copies of a loaded tree may take together: every worker holds a copy and the window of unmerged
/// results holds more, so a large state gets fewer threads (about 300 bytes per template is the estimate).
const SEED_COPIES_BUDGET_BYTES: usize = 2 << 30;
const SEED_BYTES_PER_TEMPLATE: usize = 300;

/// Threads that a parallel continuation of a loaded tree of `templates` templates may use: all the requested ones while
/// their copies of the tree fit the budget, fewer (at least one) when the tree is large.
pub fn threads_for_seed(templates: usize, requested: usize) -> usize {
    let copy = templates.saturating_mul(SEED_BYTES_PER_TEMPLATE).max(1);
    // at most 2 * threads copies are alive: one per worker and as many waiting to be merged
    (SEED_COPIES_BUDGET_BYTES / copy / 2).clamp(1, requested.max(1))
}

/// Runs the mining pipeline described by `request`.
pub fn mine(request: &MineRequest, observer: &dyn ProgressObserver) -> Result<MineOutput, EngineError> {
    let started = Instant::now();
    validate_request(request)?;
    let context = PipelineContext::new(request)?;
    let miner_config = miner_config(request)?;
    let n_runs = request.runs.len();
    let initial = load_initial(request, &miner_config)?;

    let mine_started = Instant::now();
    let (chunk_bytes, threads_requested, adaptive) = match effective_strategy(request)? {
        ExecutionStrategy::Sequential => (None, None, false),
        ExecutionStrategy::Chunked { chunk_bytes, threads } => (Some(chunk_bytes), Some(threads), false),
        // a loaded tree is the seed of every chunk, so there is no first chunk to judge the diversity by
        ExecutionStrategy::Adaptive { chunk_bytes, threads } => (Some(chunk_bytes), Some(threads), initial.is_none()),
    };
    let planned = plan::plan(request, chunk_bytes)?;
    let mut chunks = planned.units.len();
    let threads_requested = match (&initial, threads_requested) {
        (Some(seed), Some(requested)) => Some(threads_for_seed(seed.cluster_count(), requested)),
        (_, requested) => requested,
    };
    // fewer threads never change the result: the chunks are merged in order, so one thread still mines in chunks
    let parallel_training =
        threads_requested.filter(|_| (!adaptive || chunks > 1) && (initial.is_none() || chunks > 1));
    let (initial, seed) = match parallel_training {
        Some(_) => (None, initial),
        None => (initial, None),
    };
    let trained = match parallel_training {
        None => None,
        Some(requested) => {
            let options =
                chunked::ChunkOptions { threads: requested, adaptive, warm: request.warm_start, initial: seed };
            match chunked::train(&context, &miner_config, &planned, options, observer)? {
                chunked::TrainingOutcome::Merged(miner, counters, threads, merge_seconds) => {
                    Some((*miner, counters, threads, merge_seconds, "chunked"))
                }
                chunked::TrainingOutcome::TooDiverse { consumed } => {
                    let whole = plan::plan(request, None)?;
                    chunks = whole.units.len();
                    let again = adaptive::SkippingObserver::new(observer, consumed);
                    let (miner, counters) = sequential::train(&context, &miner_config, &whole, &again, None)?;
                    Some((miner, counters, 1, 0.0, "sequential"))
                }
            }
        }
    };
    let (miner, counters, threads, merge_seconds, strategy_name) = match trained {
        Some(done) => done,
        None => {
            let (miner, counters) = sequential::train(&context, &miner_config, &planned, observer, initial)?;
            (miner, counters, 1, 0.0, "sequential")
        }
    };
    let mine_seconds = mine_started.elapsed().as_secs_f64();

    let recount_started = Instant::now();
    let recounted = if request.recount {
        Some(match threads_requested {
            None => sequential::recount(&context, &miner, &planned, MatchRule::Similar, observer)?.0,
            Some(requested) => chunked::recount(&context, &miner, &planned, requested, MatchRule::Similar, observer)?.0,
        })
    } else {
        None
    };
    let recount_seconds = recount_started.elapsed().as_secs_f64();

    let freeze_started = Instant::now();
    let snapshot = request.keep_snapshot.then(|| miner.snapshot());
    let evicted = miner.evicted().to_vec();
    let (mut templates, overflowed) = match recounted {
        Some(recount) => miner.freeze_recounted(recount),
        None => {
            let flags = miner.overflowed().to_vec();
            (miner.freeze(), flags)
        }
    };
    if request.initial.is_some() {
        templates.retain(|template| template.total() > 0);
    }
    let freeze_seconds = freeze_started.elapsed().as_secs_f64();

    let runs = (0..n_runs)
        .map(|run| RunSummary {
            files: request.runs[run].len(),
            lines: counters[run].lines,
            records: counters[run].records,
            unparsed: counters[run].unparsed,
            out_of_range: counters[run].out_of_range,
            untimed: counters[run].untimed,
            bytes: planned.run_bytes[run],
            tz_aware: counters[run].tz_aware,
            overflowed: overflowed[run],
            evicted: evicted[run],
        })
        .collect();
    let metrics = RunMetrics {
        strategy: strategy_name,
        threads,
        chunks,
        wall_total_s: started.elapsed().as_secs_f64(),
        wall_mine_s: mine_seconds,
        wall_merge_s: merge_seconds,
        wall_recount_s: recount_seconds,
        wall_freeze_s: freeze_seconds,
    };
    Ok(MineOutput { runs, templates, snapshot, unmatched: None, check: None, metrics })
}

/// The strategy that a request runs with. A miner that evicts templates depends on the order of every record, so it mines
/// with one tree: the adaptive strategy becomes sequential and the chunked one is refused.
pub(crate) fn effective_strategy(request: &MineRequest) -> Result<ExecutionStrategy, EngineError> {
    match (request.mining.on_full, request.strategy) {
        (OnFull::Evict, ExecutionStrategy::Chunked { .. }) => Err(EngineError::Config(
            "on_full='evict' needs the sequential strategy: the least recently used template depends on the order of every record"
                .into(),
        )),
        (OnFull::Evict, ExecutionStrategy::Adaptive { .. }) => Ok(ExecutionStrategy::Sequential),
        (_, strategy) => Ok(strategy),
    }
}

pub(crate) fn validate_request(request: &MineRequest) -> Result<(), EngineError> {
    if request.runs.is_empty() || request.runs.iter().any(|files| files.is_empty()) {
        return Err(EngineError::Config("every run needs at least one input".into()));
    }
    if !request.windows.is_empty() && request.windows.len() != request.runs.len() {
        return Err(EngineError::Config("there must be one time window per run".into()));
    }
    Ok(())
}

pub(crate) fn miner_config(request: &MineRequest) -> Result<MinerConfig, EngineError> {
    mining_config(&request.mining)
}

pub(crate) fn mining_config(mining: &MiningConfig) -> Result<MinerConfig, EngineError> {
    Ok(MinerConfig::new(mining.depth, mining.sim_th, mining.max_children, mining.max_templates)?
        .with_on_full(mining.on_full))
}

/// Builds the miner of the saved state of `request`, after checking that it was mined with the same parameters.
pub(crate) fn load_initial(request: &MineRequest, config: &MinerConfig) -> Result<Option<DrainMiner>, EngineError> {
    load_snapshot(request.initial.as_ref(), config, request.runs.len())
}

pub(crate) fn load_snapshot(
    snapshot: Option<&MinerSnapshot>,
    config: &MinerConfig,
    n_runs: usize,
) -> Result<Option<DrainMiner>, EngineError> {
    let Some(snapshot) = snapshot else { return Ok(None) };
    if !snapshot.has_config(config) {
        return Err(EngineError::Config(
            "the saved state was mined with other parameters (depth, sim_th, max_children or max_templates)".into(),
        ));
    }
    DrainMiner::from_snapshot(snapshot.clone(), n_runs).map(|miner| Some(miner.with_on_full(config.on_full()))).map_err(
        |error| match error {
            CoreError::InvalidState(message) => EngineError::State(StateError::Damaged(message)),
            other => EngineError::Core(other),
        },
    )
}

pub(crate) fn empty_miner(config: &MinerConfig, n_runs: usize) -> DrainMiner {
    DrainMiner::new(config.clone(), n_runs)
}
