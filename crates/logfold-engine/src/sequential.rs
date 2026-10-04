use logfold_core::{DrainMiner, MinerConfig, Recount};
use logfold_io::Counters;

use crate::error::EngineError;
use crate::pipeline::{recount_unit, train_unit, Context};
use crate::plan::Plan;
use crate::request::Observer;

/// Trains a single tree on all units, in plan order.
pub(crate) fn train(
    context: &Context,
    config: &MinerConfig,
    plan: &Plan,
    observer: &dyn Observer,
) -> Result<(DrainMiner, Vec<Counters>), EngineError> {
    let n_runs = plan.run_bytes.len();
    let mut miner = crate::empty_miner(config, n_runs);
    let mut counters = vec![Counters::default(); n_runs];
    for unit in &plan.units {
        let unit_counters = train_unit(context, unit, &mut miner, observer)?;
        counters[unit.run].add(&unit_counters);
    }
    Ok((miner, counters))
}

/// Assigns the records of all units to the clusters of `miner`, in plan order.
pub(crate) fn recount(
    context: &Context,
    miner: &DrainMiner,
    plan: &Plan,
    observer: &dyn Observer,
) -> Result<Recount, EngineError> {
    let mut recount = Recount::new(plan.run_bytes.len());
    for unit in &plan.units {
        recount_unit(context, unit, miner, &mut recount, observer)?;
    }
    Ok(recount)
}
