//! Choice between the chunked and the sequential strategy from the first records of the input.
//!
//! Merging chunk trees is a serial step that costs about as much per template as training costs per record. When
//! almost every record opens a new template the merge outweighs the parallel training, and the chunked strategy is
//! slower and larger than the sequential one. The decision is taken by the first chunk after [`SAMPLE_RECORDS`]
//! records and depends only on the input, never on the thread count, so the result stays deterministic.

use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};

use logfold_core::DrainMiner;
use logfold_io::Counters;

use crate::error::EngineError;
use crate::pipeline::{Context, scan_unit};
use crate::plan::Unit;
use crate::request::Observer;

/// Number of records of the first chunk after which the strategy is chosen. A first chunk with fewer records stays
/// chunked.
pub(crate) const SAMPLE_RECORDS: u64 = 10_000;

/// The sample is diverse when it holds more than this many templates per ten records (0.3 per record).
const MAX_TEMPLATES_PER_TEN_RECORDS: u64 = 3;

/// Tells whether a sample of `records` records that produced `templates` templates is too diverse for chunked mining.
///
/// After the first 10 000 records real logs hold 0.001-0.03 templates per record (Loghub-2.0 and generated logs, with
/// and without masks); generated logs of which half of the records are new break even and logs of unique messages stand
/// at 1.0 (`bench/docs/ADAPTIVE.md`).
pub(crate) fn too_diverse(templates: usize, records: u64) -> bool {
    (templates as u64).saturating_mul(10) > records.saturating_mul(MAX_TEMPLATES_PER_TEN_RECORDS)
}

/// Trains `miner` on the first unit and gives the chunked strategy up, by stopping `tally`, when the sample is diverse.
pub(crate) fn probe_unit(
    context: &Context,
    unit: &Unit,
    miner: &mut DrainMiner,
    tally: &Tally<'_>,
) -> Result<Counters, EngineError> {
    let mut seen = 0u64;
    scan_unit(context, unit, tally, |run, tokens, meta| {
        miner.add(run, tokens, meta);
        seen += 1;
        if seen == SAMPLE_RECORDS && too_diverse(miner.cluster_count(), seen) {
            tally.stop();
        }
    })
}

/// Counts the bytes reported by the workers and cancels them when the strategy is given up.
pub(crate) struct Tally<'a> {
    inner: &'a dyn Observer,
    consumed: AtomicU64,
    stopped: AtomicBool,
}

impl<'a> Tally<'a> {
    pub(crate) fn new(inner: &'a dyn Observer) -> Self {
        Tally { inner, consumed: AtomicU64::new(0), stopped: AtomicBool::new(false) }
    }

    /// Cancels the workers that still read their chunks.
    pub(crate) fn stop(&self) {
        self.stopped.store(true, Ordering::Relaxed);
    }

    /// Tells whether [`Tally::stop`] was called.
    pub(crate) fn is_stopped(&self) -> bool {
        self.stopped.load(Ordering::Relaxed)
    }

    /// Bytes reported so far.
    pub(crate) fn consumed(&self) -> u64 {
        self.consumed.load(Ordering::Relaxed)
    }
}

impl Observer for Tally<'_> {
    fn on_bytes(&self, consumed: u64) {
        self.consumed.fetch_add(consumed, Ordering::Relaxed);
        self.inner.on_bytes(consumed);
    }

    fn cancelled(&self) -> bool {
        self.stopped.load(Ordering::Relaxed) || self.inner.cancelled()
    }
}

/// Swallows the first `skip` reported bytes, so that reading the input again does not count it twice.
pub(crate) struct Skip<'a> {
    inner: &'a dyn Observer,
    remaining: AtomicU64,
}

impl<'a> Skip<'a> {
    pub(crate) fn new(inner: &'a dyn Observer, skip: u64) -> Self {
        Skip { inner, remaining: AtomicU64::new(skip) }
    }
}

impl Observer for Skip<'_> {
    fn on_bytes(&self, consumed: u64) {
        let mut left = self.remaining.load(Ordering::Relaxed);
        loop {
            let swallowed = left.min(consumed);
            match self.remaining.compare_exchange_weak(left, left - swallowed, Ordering::Relaxed, Ordering::Relaxed) {
                Ok(_) => {
                    if consumed > swallowed {
                        self.inner.on_bytes(consumed - swallowed);
                    }
                    return;
                }
                Err(current) => left = current,
            }
        }
    }

    fn cancelled(&self) -> bool {
        self.inner.cancelled()
    }
}
