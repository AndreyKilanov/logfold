use std::collections::HashMap;

use sha2::{Digest, Sha256};

use crate::miner::Cluster;

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

fn template_id(text: &str) -> String {
    let digest = Sha256::digest(text.as_bytes());
    digest[..8].iter().map(|b| format!("{b:02x}")).collect()
}

pub(crate) fn freeze_clusters(clusters: Vec<Cluster>) -> Vec<FrozenTemplate> {
    let mut index_by_text: HashMap<String, usize> = HashMap::new();
    let mut frozen: Vec<FrozenTemplate> = Vec::new();
    for cluster in clusters {
        let mut joined: Vec<u8> = Vec::new();
        for (position, token) in cluster.tokens.iter().enumerate() {
            if position > 0 {
                joined.push(b' ');
            }
            joined.extend_from_slice(token);
        }
        let text = String::from_utf8_lossy(&joined).into_owned();
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
