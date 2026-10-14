use std::collections::HashMap;

use sha2::{Digest, Sha256};

use crate::miner::{Cluster, MinerSnapshot};
use crate::stats::RunStats;

/// A template with its per-run statistics, ready to be handed to callers.
#[derive(Clone, Debug)]
pub struct FrozenTemplate {
    /// `sha256(text)[:16 hex]`.
    pub id: String,
    /// Template text, tokens joined by a single space.
    pub text: String,
    /// Statistics per run, indexed by run.
    pub runs: Vec<crate::stats::RunStats>,
}

impl FrozenTemplate {
    /// Total number of records across runs.
    pub fn total(&self) -> u64 {
        self.runs.iter().map(|r| r.count).sum()
    }
}

/// Returns the identifier of a template: the first 16 hex digits of `sha256(text)`.
pub fn template_id(text: &str) -> String {
    let digest = Sha256::digest(text.as_bytes());
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

/// Joins the tokens of a template with single spaces, replacing invalid UTF-8.
pub(crate) fn template_text(tokens: &[Box<[u8]>]) -> String {
    let mut joined: Vec<u8> = Vec::new();
    for (position, token) in tokens.iter().enumerate() {
        if position > 0 {
            joined.push(b' ');
        }
        joined.extend_from_slice(token);
    }
    String::from_utf8_lossy(&joined).into_owned()
}

/// The templates of a saved miner with the counts, times and levels that the saved runs gave them, as a single run.
///
/// The clusters with the same text are summed, as [`DrainMiner::freeze`](crate::DrainMiner) does; the order is the same.
/// No example is kept: a saved state never holds one.
pub fn model_templates(snapshot: &MinerSnapshot) -> Vec<FrozenTemplate> {
    let clusters = snapshot.clusters.iter().chain(snapshot.overflow.iter().map(|(_, cluster)| cluster));
    let mut index_by_text: HashMap<String, usize> = HashMap::new();
    let mut frozen: Vec<FrozenTemplate> = Vec::new();
    for cluster in clusters {
        let history = &cluster.history;
        let stats = RunStats {
            count: history.count,
            first: history.first,
            last: history.last,
            levels: history.levels,
            example: None,
        };
        let text = template_text(&cluster.tokens);
        match index_by_text.get(&text) {
            Some(&index) => frozen[index].runs[0].absorb(&stats),
            None => {
                index_by_text.insert(text.clone(), frozen.len());
                frozen.push(FrozenTemplate { id: template_id(&text), text, runs: vec![stats] });
            }
        }
    }
    frozen.sort_by(|a, b| b.total().cmp(&a.total()).then_with(|| a.text.as_bytes().cmp(b.text.as_bytes())));
    frozen
}

pub(crate) fn freeze_clusters(clusters: Vec<Cluster>) -> Vec<FrozenTemplate> {
    let mut index_by_text: HashMap<String, usize> = HashMap::new();
    let mut frozen: Vec<FrozenTemplate> = Vec::new();
    for cluster in clusters {
        let text = template_text(&cluster.tokens);
        match index_by_text.get(&text) {
            Some(&index) => {
                for (dst, src) in frozen[index].runs.iter_mut().zip(cluster.stats.iter()) {
                    dst.absorb(src);
                }
            }
            None => {
                index_by_text.insert(text.clone(), frozen.len());
                frozen.push(FrozenTemplate { id: template_id(&text), text, runs: cluster.stats });
            }
        }
    }
    frozen.sort_by(|a, b| b.total().cmp(&a.total()).then_with(|| a.text.as_bytes().cmp(b.text.as_bytes())));
    frozen
}
