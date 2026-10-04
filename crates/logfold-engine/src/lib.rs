//! Application layer of logfold: the mining pipeline and its execution strategies.
//!
//! [`mine`] is the single entry point. It plans the work, runs it with the requested [`Strategy`] and returns the
//! frozen templates together with per-run counters. Parallelism is deterministic: for a fixed chunk size the result
//! does not depend on the number of threads.

#![forbid(unsafe_code)]

mod chunked;
mod error;
mod pipeline;
mod plan;
mod request;
mod sequential;

use std::time::Instant;

pub use error::EngineError;
pub use request::{
    Metrics, MineOutput, MineRequest, MiningParams, NoObserver, Observer, RunSummary, Strategy, DEFAULT_CHUNK_BYTES,
};

use logfold_core::{DrainMiner, MinerConfig};
use pipeline::Context;

/// Runs the mining pipeline described by `request`.
pub fn mine(request: &MineRequest, observer: &dyn Observer) -> Result<MineOutput, EngineError> {
    let started = Instant::now();
    if request.runs.is_empty() || request.runs.iter().any(|files| files.is_empty()) {
        return Err(EngineError::Config("every run needs at least one input".into()));
    }
    let context = Context::new(request)?;
    let miner_config = MinerConfig::new(
        request.mining.depth,
        request.mining.sim_th,
        request.mining.max_children,
        request.mining.max_templates,
    )?;
    let n_runs = request.runs.len();

    let mine_started = Instant::now();
    let (chunk_bytes, threads_requested) = match request.strategy {
        Strategy::Sequential => (None, None),
        Strategy::Chunked { chunk_bytes, threads } => (Some(chunk_bytes), Some(threads)),
    };
    let planned = plan::plan(request, chunk_bytes)?;
    let chunks = planned.units.len();
    let (miner, counters, threads, merge_seconds) = match threads_requested {
        None => {
            let (miner, counters) = sequential::train(&context, &miner_config, &planned, observer)?;
            (miner, counters, 1, 0.0)
        }
        Some(requested) => chunked::train(&context, &miner_config, &planned, requested, observer)?,
    };
    let mine_seconds = mine_started.elapsed().as_secs_f64();

    let recount_started = Instant::now();
    let recounted = if request.recount {
        Some(match threads_requested {
            None => sequential::recount(&context, &miner, &planned, observer)?,
            Some(requested) => chunked::recount(&context, &miner, &planned, requested, observer)?,
        })
    } else {
        None
    };
    let recount_seconds = recount_started.elapsed().as_secs_f64();

    let freeze_started = Instant::now();
    let (templates, overflowed) = match recounted {
        Some(recount) => miner.freeze_recounted(recount),
        None => {
            let flags = miner.overflowed().to_vec();
            (miner.freeze(), flags)
        }
    };
    let freeze_seconds = freeze_started.elapsed().as_secs_f64();

    let runs = (0..n_runs)
        .map(|run| RunSummary {
            files: request.runs[run].len(),
            lines: counters[run].lines,
            records: counters[run].records,
            unparsed: counters[run].unparsed,
            bytes: planned.run_bytes[run],
            tz_aware: counters[run].tz_aware,
            overflowed: overflowed[run],
        })
        .collect();
    let metrics = Metrics {
        strategy: if threads_requested.is_some() { "chunked" } else { "sequential" },
        threads,
        chunks,
        wall_total_s: started.elapsed().as_secs_f64(),
        wall_mine_s: mine_seconds,
        wall_merge_s: merge_seconds,
        wall_recount_s: recount_seconds,
        wall_freeze_s: freeze_seconds,
    };
    Ok(MineOutput { runs, templates, metrics })
}

pub(crate) fn empty_miner(config: &MinerConfig, n_runs: usize) -> DrainMiner {
    DrainMiner::new(config.clone(), n_runs)
}
