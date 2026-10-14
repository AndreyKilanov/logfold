//! Checking a log against a saved state: the records are matched, and those that fit no template are mined by themselves.

use std::time::Instant;

use logfold_core::{Assignment, MatchRule, OnFull, Recount, model_templates};
use logfold_io::Counters;

use crate::error::EngineError;
use crate::pipeline::{PipelineContext, scan_unit};
use crate::types::{CheckOutput, MineOutput, MineRequest, ProgressObserver, RunMetrics, RunSummary};
use crate::{empty_miner, load_initial, miner_config, plan, validate_request};

const NEEDS_STATE: &str = "checking needs a saved state";
const NO_EVICT: &str = "checking needs a state mined with on_full='pool': the identifier of a template that is evicted \
                        and mined again is not stable";

/// Assigns the records of `request` to the templates of its saved state, `initial`, and mines the records that fit no
/// template by themselves, into an empty tree with the same parameters.
///
/// The output is the one of [`crate::match_records`] (the templates that were hit with the counts of these records only,
/// the records that matched no template counted by length) and [`MineOutput::check`]: the templates of the state with
/// the counts that it saved, and the new templates that the unmatched records form. A record that fits no template of
/// the state cannot join one of them while it is mined, so every template of the second kind is new, and none of the
/// first kind changes its text or identifier. The saved state is not changed. The files are read in one pass, in order;
/// the memory beyond the loaded tree is the second tree, which `max_templates` bounds like any other.
pub fn check_records(request: &MineRequest, observer: &dyn ProgressObserver) -> Result<MineOutput, EngineError> {
    let started = Instant::now();
    validate_request(request)?;
    let context = PipelineContext::new(request)?;
    let config = miner_config(request)?;
    if config.on_full() == OnFull::Evict {
        return Err(EngineError::Config(NO_EVICT.into()));
    }
    let n_runs = request.runs.len();
    let miner = load_initial(request, &config)?.ok_or_else(|| EngineError::Config(NEEDS_STATE.into()))?;
    let model = request.initial.as_ref().map(model_templates).unwrap_or_default();

    let planned = plan::plan(request, None)?;
    let scan_started = Instant::now();
    let mut recount = Recount::with_rule(n_runs, MatchRule::Similar);
    let mut fresh = empty_miner(&config, n_runs);
    let mut counters = vec![Counters::default(); n_runs];
    for unit in &planned.units {
        let unit_counters = scan_unit(&context, unit, observer, |run, tokens, meta| {
            if let Assignment::Unmatched(_) = recount.record(&miner, run, tokens, meta) {
                fresh.add(run, tokens, meta);
            }
        })?;
        counters[unit.run].add(&unit_counters);
    }
    let scan_seconds = scan_started.elapsed().as_secs_f64();

    let freeze_started = Instant::now();
    let unmatched = recount.take_unmatched();
    let (mut templates, overflowed) = miner.freeze_recounted(recount);
    templates.retain(|template| template.total() > 0);
    let new_overflowed = fresh.overflowed().to_vec();
    let new_templates = fresh.freeze();
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
            overflowed: overflowed[run] || new_overflowed[run],
            evicted: 0,
        })
        .collect();
    let metrics = RunMetrics {
        strategy: "sequential",
        threads: 1,
        chunks: planned.units.len(),
        wall_total_s: started.elapsed().as_secs_f64(),
        wall_mine_s: 0.0,
        wall_merge_s: 0.0,
        wall_recount_s: scan_seconds,
        wall_freeze_s: freeze_seconds,
    };
    Ok(MineOutput {
        runs,
        templates,
        snapshot: None,
        unmatched: Some(unmatched),
        check: Some(CheckOutput { model, new_templates }),
        values: None,
        metrics,
    })
}
