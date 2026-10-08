//! A plain snapshot of a miner: what a state file holds, and the checks that make a snapshot safe to load.
//!
//! The snapshot knows no file format (that is the I/O crate's job) and no raw message: only parameters, the shape of the
//! tree, the templates and the counts of earlier runs. A miner rebuilt from a snapshot starts a new run with empty
//! statistics and continues exactly like the miner the snapshot was taken from (`docs/ALGORITHM.md`).

use std::collections::{BTreeMap, HashMap};

use crate::error::CoreError;
use crate::level::LEVEL_COUNT;
use crate::stats::RunStats;

use super::leaf::{INDEX_MIN_CLUSTERS, LeafIndex, Node};
use super::{Cluster, DrainMiner, MinerConfig, WILDCARD};

/// Counts of the runs that were saved with a cluster; the example line of a run is never kept.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct History {
    /// Number of records.
    pub count: u64,
    /// Smallest timestamp (microseconds), `i64::MAX` when none.
    pub first: i64,
    /// Largest timestamp (microseconds), `i64::MIN` when none.
    pub last: i64,
    /// Record counts per known level, indexed by level rank.
    pub levels: [u64; LEVEL_COUNT],
}

impl Default for History {
    fn default() -> Self {
        History { count: 0, first: i64::MAX, last: i64::MIN, levels: [0; LEVEL_COUNT] }
    }
}

impl History {
    /// Adds the counts of a run; sums saturate, because a crafted state may hold any number.
    fn add_stats(&mut self, stats: &RunStats) {
        self.count = self.count.saturating_add(stats.count);
        self.first = self.first.min(stats.first);
        self.last = self.last.max(stats.last);
        for (dst, src) in self.levels.iter_mut().zip(stats.levels.iter()) {
            *dst = dst.saturating_add(*src);
        }
    }
}

/// A template of the tree with the counts of the earlier runs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct ClusterSnapshot {
    /// Tokens of the template; a variable position holds the wildcard.
    pub tokens: Vec<Box<[u8]>>,
    /// Records of all runs saved so far, including the run that produced the snapshot.
    pub history: History,
}

/// A node of the template tree.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct NodeSnapshot {
    /// Children by token, ordered by the bytes of the token.
    pub children: Vec<(Box<[u8]>, u32)>,
    /// Ids of the clusters held by a leaf, in the order they were added.
    pub clusters: Vec<u32>,
}

/// Everything that decides how a miner places and matches the next message.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MinerSnapshot {
    /// Depth of the tree.
    pub depth: usize,
    /// Similarity threshold in millionths.
    pub threshold_micro: u64,
    /// Maximum number of children of a node.
    pub max_children: usize,
    /// Maximum number of templates before records go to the overflow templates.
    pub max_templates: usize,
    /// Nodes in the order they were created.
    pub nodes: Vec<NodeSnapshot>,
    /// Root node of every message length, ordered by length.
    pub roots: Vec<(usize, u32)>,
    /// Clusters by id.
    pub clusters: Vec<ClusterSnapshot>,
    /// Overflow template of every message length, ordered by length.
    pub overflow: Vec<(usize, ClusterSnapshot)>,
}

fn invalid(message: impl Into<String>) -> CoreError {
    CoreError::InvalidState(message.into())
}

impl Cluster {
    fn snapshot(&self) -> ClusterSnapshot {
        let mut total = self.history;
        for stats in &self.stats {
            total.add_stats(stats);
        }
        ClusterSnapshot { tokens: self.tokens.clone(), history: total }
    }

    fn from_snapshot(snapshot: ClusterSnapshot, n_runs: usize) -> Cluster {
        let mut cluster = Cluster::new(snapshot.tokens, vec![RunStats::default(); n_runs]);
        cluster.history = snapshot.history;
        cluster
    }
}

impl DrainMiner {
    /// Describes the miner as plain data. Counts of the current runs are folded into the history.
    pub fn snapshot(&self) -> MinerSnapshot {
        let nodes = self
            .nodes
            .iter()
            .map(|node| {
                let mut children: Vec<(Box<[u8]>, u32)> =
                    node.children.iter().map(|(key, child)| (key.clone(), *child)).collect();
                children.sort_by(|a, b| a.0.cmp(&b.0));
                NodeSnapshot { children, clusters: node.clusters.clone() }
            })
            .collect();
        let mut roots: Vec<(usize, u32)> = self.length_nodes.iter().map(|(length, node)| (*length, *node)).collect();
        roots.sort_unstable();
        MinerSnapshot {
            depth: self.cfg.depth,
            threshold_micro: self.cfg.threshold_micro,
            max_children: self.cfg.max_children,
            max_templates: self.cfg.max_templates,
            nodes,
            roots,
            clusters: self.clusters.iter().map(Cluster::snapshot).collect(),
            overflow: self.overflow.iter().map(|(length, cluster)| (*length, cluster.snapshot())).collect(),
        }
    }

    /// Rebuilds a miner from a snapshot that tracks `n_runs` runs with empty statistics.
    ///
    /// The snapshot is untrusted: the parameters, the shape of the tree and every id are checked, so that a damaged or
    /// crafted snapshot is refused instead of misbehaving.
    pub fn from_snapshot(snapshot: MinerSnapshot, n_runs: usize) -> Result<DrainMiner, CoreError> {
        if n_runs == 0 {
            return Err(invalid("at least one run is needed"));
        }
        let cfg = checked_config(&snapshot)?;
        let MinerSnapshot { nodes, roots, clusters, overflow, .. } = snapshot;
        if clusters.len() > cfg.max_templates {
            return Err(invalid(format!("{} templates exceed max_templates {}", clusters.len(), cfg.max_templates)));
        }
        if nodes.len() > u32::MAX as usize || clusters.len() > u32::MAX as usize {
            return Err(invalid("too many nodes or templates"));
        }
        for cluster in &clusters {
            if cluster.tokens.iter().any(|token| token.is_empty()) {
                return Err(invalid("a template has an empty token"));
            }
        }
        check_tree(&cfg, &nodes, &roots, &clusters)?;
        let overflow = checked_overflow(overflow, n_runs)?;

        let mut length_nodes: HashMap<usize, u32, ahash::RandomState> = HashMap::default();
        for (length, node) in &roots {
            length_nodes.insert(*length, *node);
        }
        let mut length_clusters: HashMap<usize, Vec<u32>, ahash::RandomState> = HashMap::default();
        for (id, cluster) in clusters.iter().enumerate() {
            length_clusters.entry(cluster.tokens.len()).or_default().push(id as u32);
        }
        let clusters: Vec<Cluster> = clusters.into_iter().map(|c| Cluster::from_snapshot(c, n_runs)).collect();
        let nodes: Vec<Node> = nodes
            .into_iter()
            .map(|node| {
                let mut built = Node { children: HashMap::default(), clusters: node.clusters, index: None };
                for (key, child) in node.children {
                    built.children.insert(key, child);
                }
                if built.clusters.len() >= INDEX_MIN_CLUSTERS {
                    let length = clusters[built.clusters[0] as usize].tokens.len();
                    let mut index = LeafIndex::new(length);
                    for &id in &built.clusters {
                        index.add(id, &clusters[id as usize].tokens);
                    }
                    built.index = Some(Box::new(index));
                }
                built
            })
            .collect();
        Ok(DrainMiner {
            cfg,
            n_runs,
            nodes,
            length_nodes,
            length_clusters,
            clusters,
            overflow,
            overflowed: vec![false; n_runs],
        })
    }
}

fn checked_config(snapshot: &MinerSnapshot) -> Result<MinerConfig, CoreError> {
    if snapshot.depth < 3 {
        return Err(invalid("depth must be at least 3"));
    }
    if snapshot.threshold_micro > 1_000_000 {
        return Err(invalid("the similarity threshold must be within [0, 1]"));
    }
    if snapshot.max_children < 1 || snapshot.max_templates < 1 {
        return Err(invalid("max_children and max_templates must be at least 1"));
    }
    Ok(MinerConfig {
        depth: snapshot.depth,
        max_children: snapshot.max_children,
        max_templates: snapshot.max_templates,
        threshold_micro: snapshot.threshold_micro,
    })
}

fn has_digit(token: &[u8]) -> bool {
    token.iter().any(u8::is_ascii_digit)
}

/// Checks that the nodes form a forest of the shape the miner builds, and that every cluster sits in exactly one leaf of
/// its own length on a path its tokens can follow.
fn check_tree(
    cfg: &MinerConfig,
    nodes: &[NodeSnapshot],
    roots: &[(usize, u32)],
    clusters: &[ClusterSnapshot],
) -> Result<(), CoreError> {
    if roots.windows(2).any(|pair| pair[0].0 >= pair[1].0) {
        return Err(invalid("the roots are not ordered by length"));
    }
    let mut visited = vec![false; nodes.len()];
    let mut placed = vec![false; clusters.len()];
    let mut path: Vec<&[u8]> = Vec::new();
    for &(length, root) in roots {
        if root as usize >= nodes.len() {
            return Err(invalid("a root points outside the nodes"));
        }
        let layers = cfg.token_layers(length);
        // (node, layer, index of the next child to visit)
        let mut stack: Vec<(u32, usize, usize)> = vec![(root, 0, 0)];
        path.clear();
        while let Some(&(node_id, layer, next)) = stack.last() {
            let node = &nodes[node_id as usize];
            if next == 0 {
                if std::mem::replace(&mut visited[node_id as usize], true) {
                    return Err(invalid("a node is reached twice"));
                }
                check_node(cfg, node, layer, layers)?;
                if layer == layers {
                    check_leaf(node, length, &path, clusters, &mut placed)?;
                }
            }
            if let Some((key, child)) = node.children.get(next) {
                if *child as usize >= nodes.len() {
                    return Err(invalid("a child points outside the nodes"));
                }
                if let Some(top) = stack.last_mut() {
                    top.2 += 1;
                }
                path.push(key);
                stack.push((*child, layer + 1, 0));
            } else {
                stack.pop();
                path.pop();
            }
        }
    }
    if visited.iter().any(|seen| !seen) {
        return Err(invalid("a node cannot be reached from a root"));
    }
    if placed.iter().any(|seen| !seen) {
        return Err(invalid("a template is in no leaf"));
    }
    Ok(())
}

fn check_node(cfg: &MinerConfig, node: &NodeSnapshot, layer: usize, layers: usize) -> Result<(), CoreError> {
    if layer < layers {
        if !node.clusters.is_empty() {
            return Err(invalid("an inner node holds templates"));
        }
    } else if !node.children.is_empty() {
        return Err(invalid("a leaf has children"));
    }
    if node.children.len() > cfg.max_children {
        return Err(invalid("a node has more children than max_children"));
    }
    for pair in node.children.windows(2) {
        if pair[0].0 >= pair[1].0 {
            return Err(invalid("the children of a node are not ordered by token"));
        }
    }
    for (key, _) in &node.children {
        if key.is_empty() {
            return Err(invalid("a child has an empty token"));
        }
        if has_digit(key) && &**key != WILDCARD {
            return Err(invalid("a token with a digit is a child of its own"));
        }
    }
    Ok(())
}

fn check_leaf(
    node: &NodeSnapshot,
    length: usize,
    path: &[&[u8]],
    clusters: &[ClusterSnapshot],
    placed: &mut [bool],
) -> Result<(), CoreError> {
    for &id in &node.clusters {
        let Some(cluster) = clusters.get(id as usize) else {
            return Err(invalid("a leaf points to a template that does not exist"));
        };
        if std::mem::replace(&mut placed[id as usize], true) {
            return Err(invalid("a template is in two leaves"));
        }
        if cluster.tokens.len() != length {
            return Err(invalid("a template is in a leaf of another length"));
        }
        for (layer, &key) in path.iter().enumerate() {
            let token: &[u8] = &cluster.tokens[layer];
            if key != WILDCARD && token != key && token != WILDCARD {
                return Err(invalid("a template does not follow the path of its leaf"));
            }
        }
    }
    Ok(())
}

fn checked_overflow(
    overflow: Vec<(usize, ClusterSnapshot)>,
    n_runs: usize,
) -> Result<BTreeMap<usize, Cluster>, CoreError> {
    if overflow.windows(2).any(|pair| pair[0].0 >= pair[1].0) {
        return Err(invalid("the overflow templates are not ordered by length"));
    }
    let mut map = BTreeMap::new();
    for (length, cluster) in overflow {
        if cluster.tokens.len() != length || cluster.tokens.iter().any(|token| &**token != WILDCARD) {
            return Err(invalid("an overflow template is not made of wildcards of its length"));
        }
        map.insert(length, Cluster::from_snapshot(cluster, n_runs));
    }
    Ok(map)
}
