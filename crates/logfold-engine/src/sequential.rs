use logfold_core::{DrainMiner, MinerConfig, Recount};
use logfold_io::Counters;

use crate::error::EngineError;
use crate::pipeline::{PipelineContext, recount_unit, train_unit};
use crate::plan::ChunkPlan;
use crate::types::ProgressObserver;

/// Trains a single tree on all units, in plan order, starting from `start` or from an empty tree.
pub(crate) fn train(
    context: &PipelineContext,
    config: &MinerConfig,
    plan: &ChunkPlan,
    observer: &dyn ProgressObserver,
    start: Option<DrainMiner>,
) -> Result<(DrainMiner, Vec<Counters>), EngineError> {
    let n_runs = plan.run_bytes.len();
    let mut miner = start.unwrap_or_else(|| crate::empty_miner(config, n_runs));
    let mut counters = vec![Counters::default(); n_runs];
    for unit in &plan.units {
        let unit_counters = train_unit(context, unit, &mut miner, observer)?;
        counters[unit.run].add(&unit_counters);
    }
    Ok((miner, counters))
}

/// Assigns the records of all units to the clusters of `miner`, in plan order; returns the counters of the scan too.
pub(crate) fn recount(
    context: &PipelineContext,
    miner: &DrainMiner,
    plan: &ChunkPlan,
    observer: &dyn ProgressObserver,
) -> Result<(Recount, Vec<Counters>), EngineError> {
    let n_runs = plan.run_bytes.len();
    let mut recount = Recount::new(n_runs);
    let mut counters = vec![Counters::default(); n_runs];
    for unit in &plan.units {
        let unit_counters = recount_unit(context, unit, miner, &mut recount, observer)?;
        counters[unit.run].add(&unit_counters);
    }
    Ok((recount, counters))
}
