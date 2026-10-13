//! Token access and scoring helpers shared by the template tree.

use crate::stats::RunStats;
use crate::tokenizer::TokenView;

use super::leaf::{INDEX_MIN_CLUSTERS, LeafIndex, LengthIndex, SCRATCH, SPARSE_LITERALS};
use super::{DrainMiner, MAX_EXAMPLE_BYTES, RecordMeta, WILDCARD};

pub(super) trait Tokens {
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

pub(super) struct BoxedTokens<'a>(pub(super) &'a [Box<[u8]>]);

impl Tokens for BoxedTokens<'_> {
    fn count(&self) -> usize {
        self.0.len()
    }
    fn at(&self, index: usize) -> &[u8] {
        &self.0[index]
    }
}

pub(super) fn has_digit(token: &[u8]) -> bool {
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
pub(super) fn score_bounded<T: Tokens>(template: &[Box<[u8]>], tokens: &T, floor: usize) -> Option<(usize, usize)> {
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

/// Counts the wildcards of `template` when every constant token equals the token of the message; `None` otherwise.
fn exact_params<T: Tokens>(template: &[Box<[u8]>], tokens: &T) -> Option<usize> {
    let mut params = 0;
    for (index, token) in template.iter().enumerate() {
        if &**token == WILDCARD {
            params += 1;
        } else if &**token != tokens.at(index) {
            return None;
        }
    }
    Some(params)
}

impl DrainMiner {
    /// The cluster among `candidates` that fits `tokens` exactly with the fewest wildcards, the earliest one on a tie.
    pub(super) fn best_exact<T: Tokens>(&self, candidates: &[u32], tokens: &T) -> Option<usize> {
        let mut best: Option<(usize, usize)> = None;
        for &index in candidates {
            let Some(params) = exact_params(&self.clusters[index as usize].tokens, tokens) else {
                continue;
            };
            if best.is_none_or(|(_, fewest)| params < fewest) {
                best = Some((index as usize, params));
                if params == 0 {
                    break;
                }
            }
        }
        best.map(|(index, _)| index)
    }
}

impl DrainMiner {
    /// The best cluster among all clusters of the token count of `tokens`, by the similarity rule of training.
    ///
    /// Many clusters of one length are searched through an inverted index of that length, built when the first record
    /// that the tree search could not place asks for it and kept up to date after that; the answer is the one of a scan
    /// of every cluster of the length ([`DrainMiner::best_in`]).
    pub(super) fn best_of_length<T: Tokens>(&self, tokens: &T) -> Option<usize> {
        let n = tokens.count();
        let clusters = self.length_clusters.get(&n).map(Vec::as_slice).unwrap_or(&[]);
        let needed = (self.cfg.threshold_micro * n as u64).div_ceil(1_000_000);
        match self.length_indexes.get(&n) {
            Some(group) if clusters.len() >= INDEX_MIN_CLUSTERS && needed >= 1 => {
                self.best_indexed(self.length_index(group, n, clusters), needed as u32, tokens)
            }
            _ => self.best_in(clusters, tokens),
        }
    }

    /// The cluster among all clusters of the token count of `tokens` that fits them exactly with the fewest wildcards,
    /// the earliest one on a tie.
    ///
    /// A cluster with more than `SPARSE_LITERALS` literal tokens that fits has all of them equal to the message's, so it
    /// is in the index lists of more positions than are left out when the longest `SPARSE_LITERALS` lists are skipped,
    /// and one walked list finds it. The clusters with fewer literals are the `sparse` ones of the length and are all
    /// tried.
    pub(super) fn best_exact_of_length<T: Tokens>(&self, tokens: &T) -> Option<usize> {
        let n = tokens.count();
        let clusters = self.length_clusters.get(&n).map(Vec::as_slice).unwrap_or(&[]);
        let Some(group) = self.length_indexes.get(&n).filter(|_| clusters.len() >= INDEX_MIN_CLUSTERS) else {
            return self.best_exact(clusters, tokens);
        };
        let index = self.length_index(group, n, clusters);
        SCRATCH.with(|cell| {
            let mut guard = cell.borrow_mut();
            let scratch = &mut *guard;
            scratch.begin(self.clusters.len());
            scratch.order.clear();
            for position in 0..n {
                if let Some(list) = index.exact[position].get(tokens.at(position)) {
                    scratch.order.push((list.len() as u32, position as u32));
                }
            }
            scratch.order.sort_unstable_by_key(|entry| std::cmp::Reverse(entry.0));
            for slot in SPARSE_LITERALS.min(scratch.order.len())..scratch.order.len() {
                let position = scratch.order[slot].1 as usize;
                let token = tokens.at(position);
                for &id in &index.exact[position][token] {
                    if &*self.clusters[id as usize].tokens[position] == token {
                        scratch.hit(id);
                    }
                }
            }
            for &id in &group.sparse {
                scratch.hit(id);
            }
            let mut best: Option<(usize, u32)> = None;
            for &id in &scratch.touched {
                let Some(params) = exact_params(&self.clusters[id as usize].tokens, tokens) else {
                    continue;
                };
                if best.is_none_or(|(fewest, first)| (params, id) < (fewest, first)) {
                    best = Some((params, id));
                }
            }
            best.map(|(_, id)| id as usize)
        })
    }

    fn length_index<'a>(&'a self, group: &'a LengthIndex, length: usize, clusters: &[u32]) -> &'a LeafIndex {
        group.index.get_or_init(|| {
            let mut index = LeafIndex::new(length);
            for &id in clusters {
                index.add(id, &self.clusters[id as usize].tokens);
            }
            index
        })
    }

    /// Finds the best cluster of the length of `tokens` twice, through the index of the length and by the plain scan.
    ///
    /// Returns `(indexed, plain)`; the two are always equal, which the tests verify (verification aid).
    pub fn fallback_both_ways(&self, tokens: &[Box<[u8]>]) -> (Option<usize>, Option<usize>) {
        let tokens = BoxedTokens(tokens);
        let clusters = self.length_clusters.get(&tokens.count()).map(Vec::as_slice).unwrap_or(&[]);
        (self.best_of_length(&tokens), self.best_in(clusters, &tokens))
    }

    /// As [`DrainMiner::fallback_both_ways`] for the exact rule (verification aid).
    pub fn exact_fallback_both_ways(&self, tokens: &[Box<[u8]>]) -> (Option<usize>, Option<usize>) {
        let tokens = BoxedTokens(tokens);
        let clusters = self.length_clusters.get(&tokens.count()).map(Vec::as_slice).unwrap_or(&[]);
        (self.best_exact_of_length(&tokens), self.best_exact(clusters, &tokens))
    }
}
