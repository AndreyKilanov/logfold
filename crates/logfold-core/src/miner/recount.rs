//! Statistics gathered by assigning records to the clusters of a finished tree.

use std::collections::{BTreeMap, HashMap};

use ahash::RandomState;

use crate::freeze::template_text;
use crate::parameters::Parameter;
use crate::stats::RunStats;
use crate::tokenizer::TokenView;
use crate::values::ValueCollector;

use super::matching::update_stats;
use super::{DrainMiner, RecordMeta};

/// How a record is assigned to a template of a finished tree.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum MatchRule {
    /// The similarity of mining (`docs/ALGORITHM.md` §9): at least the share `sim_th` of the tokens equals the constant
    /// tokens of the template.
    #[default]
    Similar,
    /// A perfect match, as `TemplateMiner.match` of Drain3: every constant token of the template equals the token of
    /// the record, and a wildcard accepts any token.
    Exact,
}

/// Result of [`DrainMiner::assign`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Assignment {
    /// The message belongs to the cluster with this index.
    Cluster(u32),
    /// No cluster matches; the payload is the token count of the message.
    Unmatched(usize),
}

impl DrainMiner {
    /// Assigns a message to a cluster of the finished tree without changing the tree, by `rule`.
    pub fn assign_with(&self, tokens: &TokenView<'_>, rule: MatchRule) -> Assignment {
        match rule {
            MatchRule::Similar => self.assign(tokens),
            MatchRule::Exact => self.assign_exact(tokens),
        }
    }

    /// Assigns a message to the cluster whose constant tokens all equal the tokens of the message.
    ///
    /// Every cluster of the same token count is considered, so the answer does not depend on the shape of the tree; the
    /// one with the fewest wildcards wins, then the earliest created.
    fn assign_exact(&self, tokens: &TokenView<'_>) -> Assignment {
        match self.best_exact_of_length(tokens) {
            Some(index) => Assignment::Cluster(index as u32),
            None => Assignment::Unmatched(tokens.len()),
        }
    }

    /// Text of the cluster `index` of an [`Assignment::Cluster`] as it is now, tokens joined by a single space.
    ///
    /// # Panics
    /// Panics when `index` was not given by [`DrainMiner::assign`] of this miner.
    pub fn cluster_text(&self, index: u32) -> String {
        template_text(&self.clusters[index as usize].tokens)
    }

    /// The tokens of the cluster `index` of an [`Assignment::Cluster`] as it is now.
    ///
    /// # Panics
    /// Panics when `index` was not given by [`DrainMiner::assign`] of this miner.
    pub fn cluster_tokens(&self, index: u32) -> &[Box<[u8]>] {
        &self.clusters[index as usize].tokens
    }

    /// The indexes of the `limit` clusters with the most records in the current runs, the most frequent first and the
    /// ones with the same count by their tokens. A cluster without a record is left out.
    pub fn top_clusters(&self, limit: usize) -> Vec<u32> {
        let mut ranked: Vec<(u64, u32)> = (0..self.clusters.len() as u32)
            .map(|index| (self.clusters[index as usize].stats.iter().map(|stats| stats.count).sum(), index))
            .filter(|(count, _)| *count > 0)
            .collect();
        ranked.sort_by(|a, b| {
            b.0.cmp(&a.0).then_with(|| self.clusters[a.1 as usize].tokens.cmp(&self.clusters[b.1 as usize].tokens))
        });
        ranked.into_iter().take(limit).map(|(_, index)| index).collect()
    }
}

/// Statistics gathered by assigning records to the clusters of a finished tree (`docs/ALGORITHM.md` §9).
pub struct Recount {
    rule: MatchRule,
    pub(crate) n_runs: usize,
    pub(crate) stats: HashMap<u32, Vec<RunStats>, RandomState>,
    pub(crate) unmatched: BTreeMap<usize, Vec<RunStats>>,
    values: Vec<ValueCollector>,
}

impl Recount {
    /// Creates an empty recount for `n_runs` runs that assigns records by similarity.
    pub fn new(n_runs: usize) -> Self {
        Self::with_rule(n_runs, MatchRule::Similar)
    }

    /// Creates an empty recount for `n_runs` runs that assigns records by `rule`.
    pub fn with_rule(n_runs: usize, rule: MatchRule) -> Self {
        Recount { rule, n_runs, stats: HashMap::default(), unmatched: BTreeMap::new(), values: Vec::new() }
    }

    /// Makes the recount also collect the values of the variable positions, for [`Recount::add_values`].
    pub fn with_values(mut self) -> Self {
        self.values = vec![ValueCollector::default(); self.n_runs];
        self
    }

    /// Counts the values that a record of run `run` gave to the variable positions of the cluster `cluster`; does
    /// nothing unless the recount was made [`with_values`](Recount::with_values).
    pub fn add_values(&mut self, run: usize, cluster: u32, parameters: &[Parameter]) {
        if let Some(collector) = self.values.get_mut(run) {
            collector.add(cluster, parameters);
        }
    }

    /// Takes the collected values out, one collector per run (none without [`with_values`](Recount::with_values)).
    pub fn take_values(&mut self) -> Vec<ValueCollector> {
        std::mem::take(&mut self.values)
    }

    /// The rule by which this recount assigns records.
    pub fn rule(&self) -> MatchRule {
        self.rule
    }

    /// Assigns one record of run `run` using `miner`, updates the statistics and tells where the record went.
    pub fn record(
        &mut self,
        miner: &DrainMiner,
        run: usize,
        tokens: &TokenView<'_>,
        rec: &RecordMeta<'_>,
    ) -> Assignment {
        let n_runs = self.n_runs;
        let assignment = miner.assign_with(tokens, self.rule);
        let slot = match assignment {
            Assignment::Cluster(index) => self.stats.entry(index).or_insert_with(|| vec![RunStats::default(); n_runs]),
            Assignment::Unmatched(length) => {
                self.unmatched.entry(length).or_insert_with(|| vec![RunStats::default(); n_runs])
            }
        };
        update_stats(&mut slot[run], rec);
        assignment
    }

    /// Takes the records that matched no cluster out of the statistics: for every run, the pairs `(token count,
    /// records)` sorted by token count, and none for a length that the run did not meet.
    ///
    /// The records are no longer counted by [`DrainMiner::freeze_recounted`], which would turn them into wildcard
    /// templates.
    pub fn take_unmatched(&mut self) -> Vec<Vec<(usize, u64)>> {
        let mut per_run = vec![Vec::new(); self.n_runs];
        for (length, run_stats) in std::mem::take(&mut self.unmatched) {
            for (item, lengths) in run_stats.iter().zip(per_run.iter_mut()) {
                if item.count > 0 {
                    lengths.push((length, item.count));
                }
            }
        }
        per_run
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
        for (mine, theirs) in self.values.iter_mut().zip(other.values) {
            mine.merge(theirs);
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
