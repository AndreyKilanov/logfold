//! Assigning records to the templates of a saved state without learning anything.

use std::time::Instant;

use crate::error::EngineError;
use crate::pipeline::PipelineContext;
use crate::types::{ExecutionStrategy, MineOutput, MineRequest, ProgressObserver, RunMetrics, RunSummary};
use crate::{chunked, load_initial, miner_config, plan, sequential, validate_request};

const NEEDS_STATE: &str = "matching needs a saved state";

/// Assigns the records of `request` to the templates of its saved state, `initial`, and learns nothing.
///
/// The result has the templates that were hit, with the counts, levels and times of these records only, and the
/// records that matched no template, counted by their length in tokens. The saved state is not changed. The strategy
/// only decides whether the files are read in parallel: matching never changes the tree, so the result does not depend
/// on it. `recount`, `warm_start` and `keep_snapshot` have no meaning here and are ignored.
pub fn match_records(request: &MineRequest, observer: &dyn ProgressObserver) -> Result<MineOutput, EngineError> {
    let started = Instant::now();
    validate_request(request)?;
    let context = PipelineContext::new(request)?;
    let config = miner_config(request)?;
    let n_runs = request.runs.len();
    let miner = load_initial(request, &config)?.ok_or_else(|| EngineError::Config(NEEDS_STATE.into()))?;

    let (chunk_bytes, threads) = match request.strategy {
        ExecutionStrategy::Sequential => (None, None),
        ExecutionStrategy::Chunked { chunk_bytes, threads } | ExecutionStrategy::Adaptive { chunk_bytes, threads } => {
            (Some(chunk_bytes), Some(threads))
        }
    };
    let planned = plan::plan(request, chunk_bytes)?;
    let match_started = Instant::now();
    let (mut recount, counters) = match threads {
        None => sequential::recount(&context, &miner, &planned, observer)?,
        Some(requested) => chunked::recount(&context, &miner, &planned, requested, observer)?,
    };
    let match_seconds = match_started.elapsed().as_secs_f64();

    let freeze_started = Instant::now();
    let unmatched = recount.take_unmatched();
    let (mut templates, overflowed) = miner.freeze_recounted(recount);
    templates.retain(|template| template.total() > 0);
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
        })
        .collect();
    let metrics = RunMetrics {
        strategy: if threads.is_some() { "chunked" } else { "sequential" },
        threads: threads.unwrap_or(1),
        chunks: planned.units.len(),
        wall_total_s: started.elapsed().as_secs_f64(),
        wall_mine_s: 0.0,
        wall_merge_s: 0.0,
        wall_recount_s: match_seconds,
        wall_freeze_s: freeze_seconds,
    };
    Ok(MineOutput { runs, templates, snapshot: None, unmatched: Some(unmatched), metrics })
}
