//! Statistics gathered by assigning records to the clusters of a finished tree.

use std::collections::{BTreeMap, HashMap};

use ahash::RandomState;

use crate::stats::RunStats;
use crate::tokenizer::TokenView;

use super::matching::update_stats;
use super::{DrainMiner, RecordMeta};

/// Result of [`DrainMiner::assign`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Assigned {
    /// The message belongs to the cluster with this index.
    Cluster(u32),
    /// No cluster matches; the payload is the token count of the message.
    Unmatched(usize),
}

/// Statistics gathered by assigning records to the clusters of a finished tree (`docs/ALGORITHM.md` §9).
pub struct Recount {
    pub(crate) n_runs: usize,
    pub(crate) stats: HashMap<u32, Vec<RunStats>, RandomState>,
    pub(crate) unmatched: BTreeMap<usize, Vec<RunStats>>,
}

impl Recount {
    /// Creates an empty recount for `n_runs` runs.
    pub fn new(n_runs: usize) -> Self {
        Recount { n_runs, stats: HashMap::default(), unmatched: BTreeMap::new() }
    }

    /// Assigns one record of run `run` using `miner` and updates the statistics.
    pub fn record(&mut self, miner: &DrainMiner, run: usize, tokens: &TokenView<'_>, rec: &RecordMeta<'_>) {
        let n_runs = self.n_runs;
        let slot = match miner.assign(tokens) {
            Assigned::Cluster(index) => self.stats.entry(index).or_insert_with(|| vec![RunStats::default(); n_runs]),
            Assigned::Unmatched(length) => {
                self.unmatched.entry(length).or_insert_with(|| vec![RunStats::default(); n_runs])
            }
        };
        update_stats(&mut slot[run], rec);
    }

    /// Merges the statistics of a later part of the input into `self`.
    pub fn merge(&mut self, other: Recount) {
        for (index, run_stats) in other.stats {
            match self.stats.get_mut(&index) {
                Some(mine) => absorb_all(mine, &run_stats),
                None => {
                    self.stats.insert(index, run_stats);
                }
            }
        }
        for (length, run_stats) in other.unmatched {
            match self.unmatched.get_mut(&length) {
                Some(mine) => absorb_all(mine, &run_stats),
                None => {
                    self.unmatched.insert(length, run_stats);
                }
            }
        }
    }
}

fn absorb_all(mine: &mut [RunStats], theirs: &[RunStats]) {
    for (dst, src) in mine.iter_mut().zip(theirs.iter()) {
        dst.absorb(src);
    }
}
