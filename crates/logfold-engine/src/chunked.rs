use std::collections::BTreeMap;
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::mpsc;
use std::time::{Duration, Instant};

use logfold_core::{DrainMiner, MinerConfig, Recount};
use logfold_io::Counters;

use crate::adaptive::{probe_unit, Tally};
use crate::error::EngineError;
use crate::pipeline::{recount_unit, train_unit, Context};
use crate::plan::Plan;
use crate::request::Observer;

/// Runs `work(index)` for `0..total` on `threads` workers and folds the results strictly in index order.
///
/// A worker may start item `i` only while `i < folded + window`, which bounds the number of unfolded results held
/// in memory. The fold order is fixed, so the outcome does not depend on scheduling or thread count. Returns the
/// number of threads used, the time spent folding on the calling thread and whether `is_stopped` ended the run.
///
/// `is_stopped` is asked whenever a result arrives; once it returns `true` the run ends without folding any more
/// results, and the workers drop the units they have started.
fn ordered_reduce<R: Send>(
    total: usize,
    threads: usize,
    observer: &dyn Observer,
    work: &(dyn Fn(usize) -> Result<R, EngineError> + Sync),
    is_stopped: impl Fn() -> bool,
    mut fold: impl FnMut(usize, R),
) -> Result<(usize, f64, bool), EngineError> {
    let threads = threads.max(1).min(total.max(1));
    let window = threads * 2;
    let next = AtomicUsize::new(0);
    let folded = AtomicUsize::new(0);
    let abort = AtomicBool::new(false);
    let (sender, receiver) = mpsc::channel::<(usize, Result<R, EngineError>)>();
    let mut fold_seconds = 0.0;
    let mut failure: Option<EngineError> = None;
    let mut stopped = false;

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
                    if is_stopped() {
                        stopped = true;
                        break;
                    }
                    if observer.cancelled() {
                        failure = Some(EngineError::Cancelled);
                        abort.store(true, Ordering::Relaxed);
                        break;
                    }
                    continue;
                }
                Err(mpsc::RecvTimeoutError::Disconnected) => break,
            };
            if is_stopped() {
                stopped = true;
                break;
            }
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
        None => Ok((threads, fold_seconds, stopped)),
    }
}

/// What [`train`] produced.
pub(crate) enum Trained {
    /// The merged tree, the counters per run, the threads used and the time spent merging.
    Merged(Box<DrainMiner>, Vec<Counters>, usize, f64),
    /// The first chunk was too diverse for this strategy; `consumed` input bytes were already reported.
    TooDiverse { consumed: u64 },
}

/// Trains one tree per unit in parallel and merges the trees in unit order.
///
/// With `adaptive` the first unit decides: when its tree holds too many templates after its first records (see
/// [`probe_unit`]) the run stops before anything is merged and [`Trained::TooDiverse`] is returned.
///
/// With `warm` the first unit is trained alone and every other unit starts from a copy of its tree (see
/// `docs/ALGORITHM.md` §6): the units do not begin with an empty tree, so they produce fewer stray templates, at the
/// price of a serial prefix of one chunk.
pub(crate) fn train(
    context: &Context,
    config: &MinerConfig,
    plan: &Plan,
    threads: usize,
    adaptive: bool,
    warm: bool,
    observer: &dyn Observer,
) -> Result<Trained, EngineError> {
    let n_runs = plan.run_bytes.len();
    let mut accumulator = crate::empty_miner(config, n_runs);
    let mut counters = vec![Counters::default(); n_runs];
    let tally = Tally::new(observer);
    let workers: &dyn Observer = if adaptive { &tally } else { observer };
    let warm = warm && plan.units.len() > 1;
    let mut template: Option<DrainMiner> = None;
    let mut seed_len = 0;
    if warm {
        let mut seed = crate::empty_miner(config, n_runs);
        let scanned = if adaptive {
            probe_unit(context, &plan.units[0], &mut seed, &tally)
        } else {
            train_unit(context, &plan.units[0], &mut seed, observer)
        };
        match scanned {
            Ok(unit) => counters[plan.units[0].run].add(&unit),
            Err(EngineError::Cancelled) if tally.is_stopped() => {
                return Ok(Trained::TooDiverse { consumed: tally.consumed() });
            }
            Err(error) => return Err(error),
        }
        seed_len = seed.cluster_count();
        template = Some(seed.warm_copy());
        accumulator = seed;
    }
    let first = usize::from(warm);
    let work = |index: usize| -> Result<(DrainMiner, Counters), EngineError> {
        let mut miner = match &template {
            Some(seed) => seed.clone(),
            None => crate::empty_miner(config, n_runs),
        };
        let unit_counters = if adaptive && index == 0 && !warm {
            probe_unit(context, &plan.units[index], &mut miner, &tally)?
        } else {
            train_unit(context, &plan.units[index + first], &mut miner, workers)?
        };
        Ok((miner, unit_counters))
    };
    let (used, merge_seconds, stopped) = ordered_reduce(
        plan.units.len() - first,
        threads,
        observer,
        &work,
        || tally.is_stopped(),
        |index, (miner, unit)| {
            counters[plan.units[index + first].run].add(&unit);
            if warm {
                accumulator.merge_warm(miner, seed_len);
            } else {
                accumulator.merge(miner);
            }
        },
    )?;
    if stopped {
        return Ok(Trained::TooDiverse { consumed: tally.consumed() });
    }
    Ok(Trained::Merged(Box::new(accumulator), counters, used, merge_seconds))
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
    ordered_reduce(
        plan.units.len(),
        threads,
        observer,
        &work,
        || false,
        |_index, partial| {
            accumulator.merge(partial);
        },
    )?;
    Ok(accumulator)
}
