use std::collections::{BTreeMap, HashMap};

use ahash::RandomState;

use crate::error::CoreError;
use crate::freeze::{FrozenTemplate, freeze_clusters};
use crate::level::Level;
use crate::stats::RunStats;
use crate::tokenizer::TokenView;

mod leaf;
mod matching;
mod merging;
mod recount;
mod snapshot;

use leaf::{INDEX_MIN_CLUSTERS, LeafIndex, Node, SCRATCH};
use matching::{BoxedTokens, Tokens, has_digit, score_bounded, update_stats};
pub use recount::{Assignment, Recount};
pub use snapshot::{ClusterHistory, ClusterSnapshot, MinerSnapshot, NodeSnapshot};

/// Token that stands for a variable part of a template.
pub const WILDCARD: &[u8] = b"<*>";

/// Maximum number of bytes kept as a per-run example of a template.
pub const MAX_EXAMPLE_BYTES: usize = 2000;

/// Parameters of the template tree.
#[derive(Clone, Debug)]
pub struct MinerConfig {
    depth: usize,
    max_children: usize,
    max_templates: usize,
    threshold_micro: u64,
}

impl MinerConfig {
    /// Validates and builds a configuration (see `docs/ALGORITHM.md` §4).
    pub fn new(depth: usize, sim_th: f64, max_children: usize, max_templates: usize) -> Result<Self, CoreError> {
        if depth < 3 {
            return Err(CoreError::InvalidConfig("depth must be at least 3".into()));
        }
        if !(0.0..=1.0).contains(&sim_th) {
            return Err(CoreError::InvalidConfig("sim_th must be within [0, 1]".into()));
        }
        if max_children < 1 {
            return Err(CoreError::InvalidConfig("max_children must be at least 1".into()));
        }
        if max_templates < 1 {
            return Err(CoreError::InvalidConfig("max_templates must be at least 1".into()));
        }
        let threshold_micro = (sim_th * 1_000_000.0 + 0.5).floor() as u64;
        Ok(MinerConfig { depth, max_children, max_templates, threshold_micro })
    }

    fn token_layers(&self, n: usize) -> usize {
        if n == 0 { 0 } else { (self.depth - 3).min(n - 1) }
    }
}

impl Default for MinerConfig {
    fn default() -> Self {
        MinerConfig { depth: 4, max_children: 100, max_templates: 100_000, threshold_micro: 400_000 }
    }
}

/// Per-record data the miner needs besides the tokens.
#[derive(Clone, Copy, Debug)]
pub struct RecordMeta<'a> {
    /// Raw message before masking (used for the example).
    pub message: &'a [u8],
    /// Timestamp in microseconds since the Unix epoch.
    pub timestamp: Option<i64>,
    /// Normalized level.
    pub level: Option<Level>,
}

#[derive(Clone)]
pub(crate) struct Cluster {
    pub(crate) tokens: Vec<Box<[u8]>>,
    pub(crate) stats: Vec<RunStats>,
    /// Counts of earlier runs that were saved with the tree; never part of a report of the current run.
    pub(crate) history: ClusterHistory,
    wild: u32,
}

impl Cluster {
    pub(crate) fn new(tokens: Vec<Box<[u8]>>, stats: Vec<RunStats>) -> Self {
        let wild = tokens.iter().filter(|t| &***t == WILDCARD).count() as u32;
        Cluster { tokens, stats, history: ClusterHistory::default(), wild }
    }
}

/// Drain-compatible template miner (see `docs/ALGORITHM.md` §4).
#[derive(Clone)]
pub struct DrainMiner {
    cfg: MinerConfig,
    n_runs: usize,
    nodes: Vec<Node>,
    length_nodes: HashMap<usize, u32, RandomState>,
    length_clusters: HashMap<usize, Vec<u32>, RandomState>,
    clusters: Vec<Cluster>,
    overflow: BTreeMap<usize, Cluster>,
    overflowed: Vec<bool>,
}

impl DrainMiner {
    /// Creates an empty miner that tracks statistics for `n_runs` runs.
    pub fn new(cfg: MinerConfig, n_runs: usize) -> Self {
        DrainMiner {
            cfg,
            n_runs,
            nodes: Vec::new(),
            length_nodes: HashMap::default(),
            length_clusters: HashMap::default(),
            clusters: Vec::new(),
            overflow: BTreeMap::new(),
            overflowed: vec![false; n_runs],
        }
    }

    /// Number of clusters in the tree (overflow clusters excluded).
    pub fn cluster_count(&self) -> usize {
        self.clusters.len()
    }

    /// Tells whether at least one leaf of the tree has an inverted index (verification aid).
    pub fn has_indexed_leaf(&self) -> bool {
        self.nodes.iter().any(|node| node.index.is_some())
    }

    /// Finds the best cluster for `tokens` twice, with the indexed search and with the plain scan of the leaf.
    ///
    /// Returns `(indexed, plain)`; the two are always equal, which the tests verify (verification aid).
    pub fn match_both_ways(&self, tokens: &[Box<[u8]>]) -> (Option<usize>, Option<usize>) {
        let tokens = BoxedTokens(tokens);
        let plain = self.search(&tokens).and_then(|leaf| self.best_in(&self.nodes[leaf as usize].clusters, &tokens));
        (self.find_match(&tokens), plain)
    }

    /// Per-run flags: true when records of the run fell into overflow clusters.
    pub fn overflowed(&self) -> &[bool] {
        &self.overflowed
    }

    /// Adds one record of run `run`.
    pub fn add(&mut self, run: usize, tokens: &TokenView<'_>, rec: &RecordMeta<'_>) {
        if let Some(index) = self.find_match(tokens) {
            self.generalize(index, tokens);
            update_stats(&mut self.clusters[index].stats[run], rec);
            return;
        }
        let mut stats = vec![RunStats::default(); self.n_runs];
        update_stats(&mut stats[run], rec);
        let template: Vec<Box<[u8]>> = (0..tokens.len()).map(|i| Box::from(tokens.get(i))).collect();
        self.insert_cluster(Cluster::new(template, stats));
    }

    /// Assigns a message to a cluster of the finished tree without changing the tree.
    ///
    /// The tree search of training comes first; when it finds nothing, every cluster of the same length is scanned
    /// (see `docs/ALGORITHM.md` §9). A message that still matches nothing is [`Assignment::Unmatched`].
    pub fn assign(&self, tokens: &TokenView<'_>) -> Assignment {
        if let Some(index) = self.find_match(tokens) {
            return Assignment::Cluster(index as u32);
        }
        match self.best_in(self.length_clusters.get(&tokens.len()).map(Vec::as_slice).unwrap_or(&[]), tokens) {
            Some(index) => Assignment::Cluster(index as u32),
            None => Assignment::Unmatched(tokens.len()),
        }
    }

    /// Consumes the miner and returns unique templates whose statistics come from `recount`.
    ///
    /// The statistics gathered while training are discarded; clusters nobody was assigned to disappear.
    pub fn freeze_recounted(self, recount: Recount) -> (Vec<FrozenTemplate>, Vec<bool>) {
        let Recount { n_runs, mut stats, unmatched } = recount;
        let mut flags = self.overflowed.clone();
        flags.resize(n_runs, false);
        let mut ordered: Vec<Cluster> = Vec::new();
        for (index, cluster) in self.clusters.into_iter().enumerate() {
            if let Some(run_stats) = stats.remove(&(index as u32)) {
                ordered.push(Cluster::new(cluster.tokens, run_stats));
            }
        }
        for (length, run_stats) in unmatched {
            for (run, item) in run_stats.iter().enumerate() {
                if item.count > 0 {
                    flags[run] = true;
                }
            }
            let tokens = (0..length).map(|_| Box::from(WILDCARD)).collect();
            ordered.push(Cluster::new(tokens, run_stats));
        }
        (freeze_clusters(ordered), flags)
    }

    /// Consumes the miner and returns unique templates sorted by total count.
    pub fn freeze(self) -> Vec<FrozenTemplate> {
        let mut ordered: Vec<Cluster> = self.clusters;
        ordered.extend(self.overflow.into_values());
        freeze_clusters(ordered)
    }

    fn find_match<T: Tokens>(&self, tokens: &T) -> Option<usize> {
        let leaf = self.search(tokens)?;
        let node = &self.nodes[leaf as usize];
        if let Some(index) = &node.index {
            let needed = (self.cfg.threshold_micro * tokens.count() as u64).div_ceil(1_000_000);
            if needed >= 1 {
                return self.best_indexed(index, needed as u32, tokens);
            }
        }
        self.best_in(&node.clusters, tokens)
    }

    /// Same result as [`Self::best_in`] over the leaf's clusters, found through the inverted index.
    ///
    /// A cluster reaches the threshold only if it holds the message's token at `needed` or more positions. Leave out the
    /// `needed - 1` positions whose index lists are the longest: such a cluster still appears in the list of at least one
    /// remaining position, so only those lists are walked. The tokens behind the long lists are the ones that most
    /// clusters of a leaf share (a constant first token, a month, a host), so skipping them is what keeps a large leaf
    /// cheap. The clusters found are then completed by comparing the left-out positions directly, which gives the same
    /// totals as a full walk and therefore the same winner (most exact matches, then most wildcards, then the earliest
    /// cluster).
    fn best_indexed<T: Tokens>(&self, index: &LeafIndex, needed: u32, tokens: &T) -> Option<usize> {
        SCRATCH.with(|cell| {
            let mut guard = cell.borrow_mut();
            let scratch = &mut *guard;
            scratch.begin(self.clusters.len());
            scratch.order.clear();
            for position in 0..tokens.count() {
                if let Some(list) = index.exact[position].get(tokens.at(position)) {
                    scratch.order.push((list.len() as u32, position as u32));
                }
            }
            let listed = scratch.order.len();
            if listed < needed as usize {
                return None;
            }
            let skip = needed as usize - 1;
            if skip > 0 {
                scratch.order.select_nth_unstable_by(skip - 1, |a, b| b.0.cmp(&a.0));
            }
            scratch.skipped.clear();
            for slot in 0..skip {
                let position = scratch.order[slot].1;
                scratch.skipped.push(position);
            }
            for slot in skip..listed {
                let position = scratch.order[slot].1 as usize;
                let token = tokens.at(position);
                if let Some(list) = index.exact[position].get(token) {
                    for &id in list {
                        if &*self.clusters[id as usize].tokens[position] == token {
                            scratch.hit(id);
                        }
                    }
                }
            }
            let mut best: Option<(u32, u32, u32)> = None;
            for &id in &scratch.touched {
                let cluster = &self.clusters[id as usize];
                let mut total = scratch.total[id as usize];
                if total + (skip as u32) < needed {
                    continue;
                }
                for &position in &scratch.skipped {
                    // A position with an index list holds a literal token, never the wildcard, so equality is a match.
                    if &*cluster.tokens[position as usize] == tokens.at(position as usize) {
                        total += 1;
                    }
                }
                if total < needed {
                    continue;
                }
                let params = cluster.wild;
                let better = match best {
                    None => true,
                    Some((best_id, best_total, best_params)) => {
                        total > best_total
                            || (total == best_total
                                && (params > best_params || (params == best_params && id < best_id)))
                    }
                };
                if better {
                    best = Some((id, total, params));
                }
            }
            best.map(|(id, _, _)| id as usize)
        })
    }

    fn best_in<T: Tokens>(&self, candidates: &[u32], tokens: &T) -> Option<usize> {
        let n = tokens.count();
        let needed = (self.cfg.threshold_micro * n as u64).div_ceil(1_000_000) as usize;
        let mut best: Option<(usize, usize, usize)> = None;
        for &index in candidates {
            let floor = best.map_or(needed, |(_, exact, _)| exact.max(needed));
            let Some((exact, params)) = score_bounded(&self.clusters[index as usize].tokens, tokens, floor) else {
                continue;
            };
            let better = match best {
                None => true,
                Some((_, best_exact, best_params)) => {
                    exact > best_exact || (exact == best_exact && params > best_params)
                }
            };
            if better {
                best = Some((index as usize, exact, params));
                if exact == n && params == 0 {
                    break;
                }
            }
        }
        best.map(|(index, _, _)| index)
    }

    fn search<T: Tokens>(&self, tokens: &T) -> Option<u32> {
        let n = tokens.count();
        let mut node = *self.length_nodes.get(&n)?;
        for layer in 0..self.cfg.token_layers(n) {
            let token = tokens.at(layer);
            let children = &self.nodes[node as usize].children;
            let next = if has_digit(token) {
                children.get(WILDCARD)
            } else {
                children.get(token).or_else(|| children.get(WILDCARD))
            };
            node = *next?;
        }
        Some(node)
    }

    fn new_node(&mut self) -> u32 {
        self.nodes.push(Node::default());
        (self.nodes.len() - 1) as u32
    }

    fn insert_path<T: Tokens>(&mut self, tokens: &T) -> u32 {
        let n = tokens.count();
        let mut node = match self.length_nodes.get(&n) {
            Some(&index) => index,
            None => {
                let index = self.new_node();
                self.length_nodes.insert(n, index);
                index
            }
        };
        for layer in 0..self.cfg.token_layers(n) {
            let token = tokens.at(layer);
            let key: &[u8] = if has_digit(token) { WILDCARD } else { token };
            let existing = self.nodes[node as usize].children.get(key).copied();
            node = match existing {
                Some(child) => child,
                None => {
                    let len = self.nodes[node as usize].children.len();
                    let has_wildcard = self.nodes[node as usize].children.contains_key(WILDCARD);
                    let create_key: Option<&[u8]> = if key == WILDCARD {
                        Some(WILDCARD)
                    } else if has_wildcard {
                        (len < self.cfg.max_children).then_some(key)
                    } else if len + 1 < self.cfg.max_children {
                        Some(key)
                    } else {
                        Some(WILDCARD)
                    };
                    match create_key {
                        Some(new_key) => {
                            let child = self.new_node();
                            self.nodes[node as usize].children.insert(Box::from(new_key), child);
                            child
                        }
                        None => self.nodes[node as usize].children[WILDCARD],
                    }
                }
            };
        }
        node
    }

    fn insert_cluster(&mut self, cluster: Cluster) {
        if self.clusters.len() >= self.cfg.max_templates {
            let length = cluster.tokens.len();
            for (run, stats) in cluster.stats.iter().enumerate() {
                if stats.count > 0 {
                    self.overflowed[run] = true;
                }
            }
            match self.overflow.get_mut(&length) {
                Some(mine) => {
                    for (dst, src) in mine.stats.iter_mut().zip(cluster.stats.iter()) {
                        dst.absorb(src);
                    }
                }
                None => {
                    let tokens = (0..length).map(|_| Box::from(WILDCARD)).collect();
                    self.overflow.insert(length, Cluster::new(tokens, cluster.stats));
                }
            }
            return;
        }
        let leaf = self.insert_path(&BoxedTokens(&cluster.tokens));
        let id = self.clusters.len() as u32;
        let node = &mut self.nodes[leaf as usize];
        node.clusters.push(id);
        match node.index.as_mut() {
            Some(index) => index.add(id, &cluster.tokens),
            None if node.clusters.len() >= INDEX_MIN_CLUSTERS => {
                let mut index = LeafIndex::new(cluster.tokens.len());
                for &member in &node.clusters {
                    if member != id {
                        index.add(member, &self.clusters[member as usize].tokens);
                    }
                }
                index.add(id, &cluster.tokens);
                node.index = Some(Box::new(index));
            }
            None => {}
        }
        self.length_clusters.entry(cluster.tokens.len()).or_default().push(id);
        self.clusters.push(cluster);
    }

    fn generalize<T: Tokens>(&mut self, index: usize, tokens: &T) {
        let cluster = &mut self.clusters[index];
        for (position, template_token) in cluster.tokens.iter_mut().enumerate() {
            if &**template_token != WILDCARD && &**template_token != tokens.at(position) {
                *template_token = Box::from(WILDCARD);
                cluster.wild += 1;
            }
        }
    }
}
