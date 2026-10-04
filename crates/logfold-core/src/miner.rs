use std::collections::{BTreeMap, HashMap};

use ahash::RandomState;

use crate::error::CoreError;
use crate::freeze::{freeze_clusters, FrozenTemplate};
use crate::level::Level;
use crate::stats::RunStats;
use crate::tokenizer::TokenView;

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
        if n == 0 {
            0
        } else {
            (self.depth - 3).min(n - 1)
        }
    }
}

impl Default for MinerConfig {
    fn default() -> Self {
        MinerConfig::new(4, 0.4, 100, 100_000).expect("default configuration is valid")
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

pub(crate) struct Cluster {
    pub(crate) tokens: Vec<Box<[u8]>>,
    pub(crate) stats: Vec<RunStats>,
    wild: u32,
}

impl Cluster {
    pub(crate) fn new(tokens: Vec<Box<[u8]>>, stats: Vec<RunStats>) -> Self {
        let wild = tokens.iter().filter(|t| &***t == WILDCARD).count() as u32;
        Cluster { tokens, stats, wild }
    }
}

/// Leaves with at least this many clusters get an inverted index so that matching does not scan them linearly.
const INDEX_MIN_CLUSTERS: usize = 16;

/// Inverted index of a leaf: for every token position, the clusters that hold a given literal token.
///
/// Entries are never removed. An entry becomes stale when its position is generalized; readers verify the
/// cluster's current token, so a stale entry is simply ignored. Wildcards never count as matches, so they are not
/// indexed.
struct LeafIndex {
    exact: Vec<HashMap<Box<[u8]>, Vec<u32>, RandomState>>,
}

impl LeafIndex {
    fn new(length: usize) -> Self {
        LeafIndex { exact: (0..length).map(|_| HashMap::default()).collect() }
    }

    fn add(&mut self, id: u32, tokens: &[Box<[u8]>]) {
        for (position, token) in tokens.iter().enumerate() {
            if &**token != WILDCARD {
                self.exact[position].entry(token.clone()).or_default().push(id);
            }
        }
    }
}

#[derive(Default)]
struct Node {
    children: HashMap<Box<[u8]>, u32, RandomState>,
    clusters: Vec<u32>,
    index: Option<Box<LeafIndex>>,
}

/// Per-thread counters reused by indexed matching; a generation stamp avoids clearing between calls.
#[derive(Default)]
struct Scratch {
    stamp: u32,
    seen: Vec<u32>,
    total: Vec<u32>,
    touched: Vec<u32>,
}

impl Scratch {
    fn begin(&mut self, clusters: usize) {
        self.stamp = self.stamp.wrapping_add(1);
        if self.stamp == 0 {
            self.seen.fill(0);
            self.stamp = 1;
        }
        if self.seen.len() < clusters {
            self.seen.resize(clusters, 0);
            self.total.resize(clusters, 0);
        }
        self.touched.clear();
    }

    fn hit(&mut self, id: u32) {
        let slot = id as usize;
        if self.seen[slot] != self.stamp {
            self.seen[slot] = self.stamp;
            self.total[slot] = 0;
            self.touched.push(id);
        }
        self.total[slot] += 1;
    }
}

thread_local! {
    static SCRATCH: std::cell::RefCell<Scratch> = std::cell::RefCell::new(Scratch::default());
}

trait Tokens {
    fn count(&self) -> usize;
    fn at(&self, index: usize) -> &[u8];
}

impl Tokens for TokenView<'_> {
    fn count(&self) -> usize {
        self.len()
    }
    fn at(&self, index: usize) -> &[u8] {
        self.get(index)
    }
}

struct BoxedTokens<'a>(&'a [Box<[u8]>]);

impl Tokens for BoxedTokens<'_> {
    fn count(&self) -> usize {
        self.0.len()
    }
    fn at(&self, index: usize) -> &[u8] {
        &self.0[index]
    }
}

fn has_digit(token: &[u8]) -> bool {
    token.iter().any(u8::is_ascii_digit)
}

fn truncate_example(message: &[u8]) -> Box<[u8]> {
    let text = String::from_utf8_lossy(message);
    let mut end = text.len().min(MAX_EXAMPLE_BYTES);
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    Box::from(text[..end].as_bytes())
}

pub(crate) fn update_stats(stats: &mut RunStats, rec: &RecordMeta<'_>) {
    stats.count += 1;
    if let Some(ts) = rec.timestamp {
        stats.first = stats.first.min(ts);
        stats.last = stats.last.max(ts);
    }
    if let Some(level) = rec.level {
        stats.levels[level.rank()] += 1;
    }
    if stats.example.is_none() {
        stats.example = Some(truncate_example(rec.message));
    }
}

/// Scores `template` against `tokens`; gives up (`None`) as soon as the exact matches cannot reach `floor`.
fn score_bounded<T: Tokens>(template: &[Box<[u8]>], tokens: &T, floor: usize) -> Option<(usize, usize)> {
    let n = template.len();
    let mut exact = 0;
    let mut params = 0;
    for (index, token) in template.iter().enumerate() {
        if &**token == WILDCARD {
            params += 1;
        } else if &**token == tokens.at(index) {
            exact += 1;
        }
        if exact + (n - index - 1) < floor {
            return None;
        }
    }
    (exact >= floor).then_some((exact, params))
}

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

/// Drain-compatible template miner (see `docs/ALGORITHM.md` §4).
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

    /// Merges `other` into `self` in cluster creation order (see `docs/ALGORITHM.md` §6).
    pub fn merge(&mut self, other: DrainMiner) {
        assert_eq!(self.n_runs, other.n_runs, "miners must track the same runs");
        for (mine, theirs) in self.overflowed.iter_mut().zip(other.overflowed.iter()) {
            *mine |= *theirs;
        }
        for cluster in other.clusters {
            self.merge_cluster(cluster);
        }
        for (length, cluster) in other.overflow {
            match self.overflow.get_mut(&length) {
                Some(mine) => {
                    for (dst, src) in mine.stats.iter_mut().zip(cluster.stats.iter()) {
                        dst.absorb(src);
                    }
                }
                None => {
                    self.overflow.insert(length, cluster);
                }
            }
        }
    }

    /// Assigns a message to a cluster of the finished tree without changing the tree.
    ///
    /// The tree search of training comes first; when it finds nothing, every cluster of the same length is scanned
    /// (see `docs/ALGORITHM.md` §9). A message that still matches nothing is [`Assigned::Unmatched`].
    pub fn assign(&self, tokens: &TokenView<'_>) -> Assigned {
        if let Some(index) = self.find_match(tokens) {
            return Assigned::Cluster(index as u32);
        }
        match self.best_in(self.length_clusters.get(&tokens.len()).map(Vec::as_slice).unwrap_or(&[]), tokens) {
            Some(index) => Assigned::Cluster(index as u32),
            None => Assigned::Unmatched(tokens.len()),
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
    /// Only clusters sharing at least one token position with the message can reach the similarity threshold
    /// (`needed >= 1`), so only those are scored, and ties still resolve to the earliest created cluster.
    fn best_indexed<T: Tokens>(&self, index: &LeafIndex, needed: u32, tokens: &T) -> Option<usize> {
        SCRATCH.with(|cell| {
            let mut scratch = cell.borrow_mut();
            scratch.begin(self.clusters.len());
            for position in 0..tokens.count() {
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
                let total = scratch.total[id as usize];
                if total < needed {
                    continue;
                }
                let params = self.clusters[id as usize].wild;
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

    fn merge_cluster(&mut self, cluster: Cluster) {
        let matched = self.find_match(&BoxedTokens(&cluster.tokens));
        match matched {
            Some(index) => {
                self.generalize(index, &BoxedTokens(&cluster.tokens));
                for (dst, src) in self.clusters[index].stats.iter_mut().zip(cluster.stats.iter()) {
                    dst.absorb(src);
                }
            }
            None => self.insert_cluster(cluster),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::tokenizer::Tokenizer;

    fn feed(miner: &mut DrainMiner, run: usize, line: &str) {
        let tok = Tokenizer::new(b" \t\n\r").unwrap();
        let mut spans = Vec::new();
        tok.tokenize(line.as_bytes(), &mut spans);
        let view = TokenView::new(line.as_bytes(), &spans);
        miner.add(run, &view, &RecordMeta { message: line.as_bytes(), timestamp: None, level: None });
    }

    fn texts(miner: DrainMiner) -> Vec<(String, u64)> {
        miner.freeze().into_iter().map(|t| (t.text, t.runs.iter().map(|r| r.count).sum())).collect()
    }

    #[test]
    fn groups_and_generalizes() {
        let mut miner = DrainMiner::new(MinerConfig::default(), 1);
        for user in ["alice", "bob", "carol"] {
            feed(&mut miner, 0, &format!("user {user} failed login"));
        }
        feed(&mut miner, 0, "disk full on sda");
        let result = texts(miner);
        assert_eq!(result[0], ("user <*> failed login".to_string(), 3));
        assert_eq!(result[1], ("disk full on sda".to_string(), 1));
    }

    #[test]
    fn numeric_tokens_route_to_wildcard() {
        let mut miner = DrainMiner::new(MinerConfig::default(), 1);
        feed(&mut miner, 0, "42 items processed");
        feed(&mut miner, 0, "43 items processed");
        let result = texts(miner);
        assert_eq!(result, vec![("<*> items processed".to_string(), 2)]);
    }

    #[test]
    fn empty_messages_form_one_template() {
        let mut miner = DrainMiner::new(MinerConfig::default(), 1);
        feed(&mut miner, 0, "");
        feed(&mut miner, 0, "");
        assert_eq!(texts(miner), vec![(String::new(), 2)]);
    }

    #[test]
    fn counts_are_kept_per_run() {
        let mut miner = DrainMiner::new(MinerConfig::default(), 2);
        feed(&mut miner, 0, "ready");
        feed(&mut miner, 1, "ready");
        feed(&mut miner, 1, "ready");
        let frozen = miner.freeze();
        assert_eq!(frozen.len(), 1);
        assert_eq!(frozen[0].runs[0].count, 1);
        assert_eq!(frozen[0].runs[1].count, 2);
    }

    #[test]
    fn overflow_collects_excess_templates() {
        let cfg = MinerConfig::new(4, 0.4, 100, 2).unwrap();
        let mut miner = DrainMiner::new(cfg, 1);
        for line in ["a b c", "d e f", "g h i", "j k l"] {
            feed(&mut miner, 0, line);
        }
        assert!(miner.overflowed()[0]);
        let result = texts(miner);
        let total: u64 = result.iter().map(|(_, c)| c).sum();
        assert_eq!(total, 4);
        assert!(result.iter().any(|(t, c)| t == "<*> <*> <*>" && *c == 2));
    }

    #[test]
    fn merge_conserves_counts_and_matches_templates() {
        let cfg = MinerConfig::default();
        let mut left = DrainMiner::new(cfg.clone(), 1);
        let mut right = DrainMiner::new(cfg, 1);
        for user in ["alice", "bob"] {
            feed(&mut left, 0, &format!("user {user} failed login"));
        }
        for user in ["carol", "dave", "erin"] {
            feed(&mut right, 0, &format!("user {user} failed login"));
        }
        feed(&mut right, 0, "disk full on sda");
        left.merge(right);
        let result = texts(left);
        assert_eq!(result[0], ("user <*> failed login".to_string(), 5));
        assert_eq!(result[1], ("disk full on sda".to_string(), 1));
    }

    #[test]
    fn identical_input_gives_identical_output() {
        let run = || {
            let mut miner = DrainMiner::new(MinerConfig::default(), 1);
            for i in 0..200 {
                feed(&mut miner, 0, &format!("worker w{} handled request for tenant t{}", i % 7, i % 3));
                feed(&mut miner, 0, &format!("cache miss key={}", i % 11));
            }
            texts(miner)
        };
        assert_eq!(run(), run());
    }
}
