//! Per-leaf inverted index, tree nodes and the per-thread scratch of indexed matching.

use std::collections::HashMap;
use std::sync::OnceLock;

use ahash::RandomState;

use super::WILDCARD;

/// Leaves with at least this many clusters get an inverted index so that matching does not scan them linearly.
pub(super) const INDEX_MIN_CLUSTERS: usize = 16;

/// Inverted index of a leaf: for every token position, the clusters that hold a given literal token.
///
/// Entries are never removed. An entry becomes stale when its position is generalized; readers verify the
/// cluster's current token, so a stale entry is simply ignored. Wildcards never count as matches, so they are not
/// indexed.
#[derive(Clone)]
pub(super) struct LeafIndex {
    pub(super) exact: Vec<HashMap<Box<[u8]>, Vec<u32>, RandomState>>,
}

impl LeafIndex {
    pub(super) fn new(length: usize) -> Self {
        LeafIndex { exact: (0..length).map(|_| HashMap::default()).collect() }
    }

    pub(super) fn add(&mut self, id: u32, tokens: &[Box<[u8]>]) {
        for (position, token) in tokens.iter().enumerate() {
            if &**token != WILDCARD {
                self.exact[position].entry(token.clone()).or_default().push(id);
            }
        }
    }
}

/// A cluster with at most this many literal tokens is `sparse`, see [`LengthIndex::sparse`]; the exact search leaves out
/// the lists of this many positions.
pub(super) const SPARSE_LITERALS: usize = 3;

/// What is kept for one token count, for the records that the tree search cannot place.
#[derive(Default, Clone)]
pub(super) struct LengthIndex {
    /// Inverted index of every cluster of the length, built by the first record that needs it and kept up to date.
    pub(super) index: OnceLock<LeafIndex>,
    /// The clusters that hold at most [`SPARSE_LITERALS`] literal tokens. A cluster with more literals that fits a message
    /// has all of them equal to the message's, so it is found in the list of at least one position even when the lists of
    /// `SPARSE_LITERALS` other positions are left out; the clusters with fewer literals are not found that way and are
    /// listed here instead. A cluster only ever loses literals, so it enters the list once and never leaves it.
    pub(super) sparse: Vec<u32>,
}

impl LengthIndex {
    /// Notes a new cluster `id` of this length.
    pub(super) fn add(&mut self, id: u32, tokens: &[Box<[u8]>]) {
        if literals(tokens) <= SPARSE_LITERALS {
            self.sparse.push(id);
        }
        if let Some(index) = self.index.get_mut() {
            index.add(id, tokens);
        }
    }
}

/// Number of tokens that are not the wildcard.
pub(super) fn literals(tokens: &[Box<[u8]>]) -> usize {
    tokens.iter().filter(|token| &***token != WILDCARD).count()
}

#[derive(Default, Clone)]
pub(super) struct Node {
    pub(super) children: HashMap<Box<[u8]>, u32, RandomState>,
    pub(super) clusters: Vec<u32>,
    pub(super) index: Option<Box<LeafIndex>>,
}

/// Per-thread counters reused by indexed matching; a generation stamp avoids clearing between calls.
pub(super) struct Scratch {
    pub(super) stamp: u32,
    pub(super) seen: Vec<u32>,
    pub(super) total: Vec<u32>,
    pub(super) touched: Vec<u32>,
    /// `(list length, position)` of every token position of the message that has an index list.
    pub(super) order: Vec<(u32, u32)>,
    /// Positions whose lists are not walked, see [`DrainMiner::best_indexed`].
    pub(super) skipped: Vec<u32>,
}

impl Scratch {
    /// An empty scratch, usable in a `const` thread-local initializer.
    pub(super) const fn new() -> Self {
        Scratch {
            stamp: 0,
            seen: Vec::new(),
            total: Vec::new(),
            touched: Vec::new(),
            order: Vec::new(),
            skipped: Vec::new(),
        }
    }

    pub(super) fn begin(&mut self, clusters: usize) {
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

    pub(super) fn hit(&mut self, id: u32) {
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
    pub(super) static SCRATCH: std::cell::RefCell<Scratch> = const { std::cell::RefCell::new(Scratch::new()) };
}
