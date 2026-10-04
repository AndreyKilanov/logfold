use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use logfold_core::{DrainMiner, MinerConfig, Recount};
use logfold_io::Counters;

use crate::error::EngineError;
use crate::pipeline::{recount_unit, train_unit, Context};
use crate::plan::Plan;
use crate::request::Observer;

/// Runs `work(index)` for `0..total` on `threads` workers and folds the results strictly in index order.
///
/// A worker may start item `i` only while `i < folded + window`, which bounds the number of unfolded results held
/// in memory. The fold order is fixed, so the outcome does not depend on scheduling or thread count. Returns the
/// number of threads used and the time spent folding on the calling thread.
fn ordered_reduce<R: Send>(
    total: usize,
    threads: usize,
    observer: &dyn Observer,
    work: &(dyn Fn(usize) -> Result<R, EngineError> + Sync),
    mut fold: impl FnMut(usize, R),
) -> Result<(usize, f64), EngineError> {
    let threads = threads.max(1).min(total.max(1));
    let window = threads * 2;
    let next = AtomicUsize::new(0);
    let folded = AtomicUsize::new(0);
    let abort = AtomicBool::new(false);
    let (sender, receiver) = mpsc::channel::<(usize, Result<R, EngineError>)>();
    let mut fold_seconds = 0.0;
    let mut failure: Option<EngineError> = None;

    std::thread::scope(|scope| {
        for _ in 0..threads {
            let sender = sender.clone();
            let (next, folded, abort) = (&next, &folded, &abort);
            scope.spawn(move || loop {
                let index = next.fetch_add(1, Ordering::Relaxed);
                if index >= total {
                    break;
                }
                while index >= folded.load(Ordering::Acquire) + window && !abort.load(Ordering::Relaxed) {
                    std::thread::sleep(Duration::from_micros(200));
                }
                if abort.load(Ordering::Relaxed) {
                    break;
                }
                if sender.send((index, work(index))).is_err() {
                    break;
                }
            });
        }
        drop(sender);

        let mut pending: BTreeMap<usize, R> = BTreeMap::new();
        let mut expected = 0usize;
        while expected < total {
            let (index, result) = match receiver.recv_timeout(Duration::from_millis(100)) {
                Ok(message) => message,
                Err(mpsc::RecvTimeoutError::Timeout) => {
                    if observer.cancelled() {
                        failure = Some(EngineError::Cancelled);
                        abort.store(true, Ordering::Relaxed);
                        break;
                    }
                    continue;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
            };
            match result {
                Ok(value) => {
                    pending.insert(index, value);
                }
                Err(error) => {
                    failure = Some(error);
                    abort.store(true, Ordering::Relaxed);
                    break;
                }
            }
            while let Some(value) = pending.remove(&expected) {
                let started = Instant::now();
                fold(expected, value);
                fold_seconds += started.elapsed().as_secs_f64();
                expected += 1;
                folded.store(expected, Ordering::Release);
            }
        }
        abort.store(true, Ordering::Relaxed);
    });

    match failure {
        Some(error) => Err(error),
        None => Ok((threads, fold_seconds)),
    }
}

/// Trains one tree per unit in parallel and merges the trees in unit order.
pub(crate) fn train(
    context: &Context,
    config: &MinerConfig,
    plan: &Plan,
    threads: usize,
    observer: &dyn Observer,
) -> Result<(DrainMiner, Vec<Counters>, usize, f64), EngineError> {
    let n_runs = plan.run_bytes.len();
    let mut accumulator = crate::empty_miner(config, n_runs);
    let mut counters = vec![Counters::default(); n_runs];
    let work = |index: usize| -> Result<(DrainMiner, Counters), EngineError> {
        let mut miner = crate::empty_miner(config, n_runs);
        let unit_counters = train_unit(context, &plan.units[index], &mut miner, observer)?;
        Ok((miner, unit_counters))
    };
    let (used, merge_seconds) = ordered_reduce(plan.units.len(), threads, observer, &work, |index, (miner, unit)| {
        counters[plan.units[index].run].add(&unit);
        accumulator.merge(miner);
    })?;
    Ok((accumulator, counters, used, merge_seconds))
}

/// Assigns the records of every unit to the clusters of `miner` in parallel and merges the statistics in unit order.
pub(crate) fn recount(
    context: &Context,
    miner: &DrainMiner,
    plan: &Plan,
    threads: usize,
    observer: &dyn Observer,
) -> Result<Recount, EngineError> {
    let n_runs = plan.run_bytes.len();
    let mut accumulator = Recount::new(n_runs);
    let work = |index: usize| -> Result<Recount, EngineError> {
        let mut partial = Recount::new(n_runs);
        recount_unit(context, &plan.units[index], miner, &mut partial, observer)?;
        Ok(partial)
    };
    ordered_reduce(plan.units.len(), threads, observer, &work, |_index, partial| accumulator.merge(partial))?;
    Ok(accumulator)
}
