//! Which values a variable position took in each run, to tell the new ones from the gone ones (ADR-018).
//!
//! A value is kept as a 64-bit fingerprint with the number of records that gave it, about 20 bytes a value, and the
//! memory is bounded: a position keeps at most [`MAX_PER_POSITION`] different values and a collector at most `total`.
//! A position that went over a limit is marked `capped` and gives no lists, because with part of the values missing a
//! value that looks new may only be one that was not counted. Sums and unions do not depend on their order, so without
//! a cap the result is the same for any number of threads and any size of chunk.

use std::collections::{BTreeMap, HashMap};
use std::hash::{BuildHasherDefault, DefaultHasher, Hasher};
use std::sync::Arc;

use crate::values::{Slot, slot_of};

/// The number of different values that a position keeps for one run.
pub const MAX_PER_POSITION: usize = 1_000_000;
/// The number of different values that the collector of a run keeps in all positions.
pub const MAX_PER_RUN: usize = 4_000_000;
/// The number of different values that the collector of one chunk keeps in all positions.
pub const MAX_PER_CHUNK: usize = 1_000_000;
/// The number of new values, and of gone ones, that a position lists.
pub const TOP_CHANGES: usize = 10;

/// A hasher for keys that already are hashes.
#[derive(Default)]
pub(crate) struct Identity(u64);

impl Hasher for Identity {
    fn finish(&self) -> u64 {
        self.0
    }

    fn write(&mut self, bytes: &[u8]) {
        for &byte in bytes {
            self.0 = (self.0 << 8) | u64::from(byte);
        }
    }

    fn write_u64(&mut self, value: u64) {
        self.0 = value;
    }
}

type Counts = HashMap<u64, u64, BuildHasherDefault<Identity>>;

/// The 64-bit fingerprint of a value (SipHash-1-3 with a zero key, whole value).
pub fn fingerprint(value: &[u8]) -> u64 {
    let mut hasher = DefaultHasher::new();
    hasher.write(value);
    hasher.finish()
}

/// The fingerprints of the values of one position in one run, with how many records gave each.
#[derive(Clone, Debug, Default)]
pub struct ValueSet {
    counts: Counts,
    capped: bool,
}

impl ValueSet {
    /// The number of different values counted.
    pub fn len(&self) -> usize {
        self.counts.len()
    }

    /// Whether no value was counted.
    pub fn is_empty(&self) -> bool {
        self.counts.is_empty()
    }

    /// Whether a limit was hit, so that some values are missing.
    pub fn capped(&self) -> bool {
        self.capped
    }

    /// Adds the values of `other`, as far as the limit of a position allows.
    pub fn merge(&mut self, other: &ValueSet) {
        self.capped |= other.capped;
        for (&key, &count) in &other.counts {
            self.add(key, count, true);
        }
    }

    /// Adds `count` records of the value with `key`; a value that does not fit marks the set as capped.
    fn add(&mut self, key: u64, count: u64, room: bool) {
        if let Some(seen) = self.counts.get_mut(&key) {
            *seen += count;
        } else if room && self.counts.len() < MAX_PER_POSITION {
            self.counts.insert(key, count);
        } else {
            self.capped = true;
        }
    }
}

/// The values of one run, by template (the index of its cluster) and position, with a limit on the number of values.
#[derive(Clone, Debug)]
pub struct PresenceCollector {
    clusters: BTreeMap<u32, Vec<(Slot, ValueSet)>>,
    total: usize,
    limit: usize,
}

impl PresenceCollector {
    /// An empty collector that keeps at most `limit` different values in all positions.
    pub fn new(limit: usize) -> Self {
        PresenceCollector { clusters: BTreeMap::new(), total: 0, limit }
    }

    /// Counts one value of the position `position` (named `name`) of the template `cluster`.
    pub fn add(&mut self, cluster: u32, position: usize, name: &str, value: &[u8]) {
        let key = fingerprint(value);
        let room = self.total < self.limit;
        let slots = self.clusters.entry(cluster).or_default();
        let set = slot_of(slots, position, name);
        let before = set.len();
        set.add(key, 1, room);
        self.total += set.len() - before;
    }

    /// Adds the collector of another part of the input.
    pub fn merge(&mut self, other: PresenceCollector) {
        let limit = self.limit;
        let mut total = self.total;
        for (cluster, slots) in other.clusters {
            let mine = self.clusters.entry(cluster).or_default();
            for ((position, name), theirs) in slots {
                let set = slot_of(mine, position, &name);
                set.capped |= theirs.capped;
                for (key, count) in theirs.counts {
                    let before = set.len();
                    set.add(key, count, total < limit);
                    total += set.len() - before;
                }
            }
        }
        self.total = total;
    }

    /// The sets by template and position, in order.
    pub fn into_clusters(self) -> BTreeMap<u32, Vec<(Slot, ValueSet)>> {
        self.clusters
    }
}

/// How the values of one position differ between two runs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Change {
    /// The most frequent values of the second run that the first run lacks: `(fingerprint, records)`.
    pub new: Vec<(u64, u64)>,
    /// The most frequent values of the first run that the second run lacks.
    pub gone: Vec<(u64, u64)>,
    /// How many different values only the second run has.
    pub new_distinct: u64,
    /// How many different values only the first run has.
    pub gone_distinct: u64,
    /// How many different values both runs have.
    pub shared_distinct: u64,
    /// How many different values the first and the second run have.
    pub distinct: (u64, u64),
    /// Whether a limit was hit: the lists are then empty and the numbers are lower bounds.
    pub capped: bool,
}

fn top(counts: &Counts, other: &Counts) -> (Vec<(u64, u64)>, u64) {
    let mut only: Vec<(u64, u64)> =
        counts.iter().filter(|(key, _)| !other.contains_key(key)).map(|(&key, &count)| (key, count)).collect();
    let total = only.len() as u64;
    let order = |a: &(u64, u64), b: &(u64, u64)| b.1.cmp(&a.1).then_with(|| a.0.cmp(&b.0));
    if only.len() > TOP_CHANGES {
        only.select_nth_unstable_by(TOP_CHANGES - 1, order);
        only.truncate(TOP_CHANGES);
    }
    only.sort_by(order);
    (only, total)
}

/// Compares the values of one position in the first and the second run; `None` when they are the same set.
pub fn compare(before: &ValueSet, after: &ValueSet) -> Option<Change> {
    let distinct = (before.len() as u64, after.len() as u64);
    if before.capped || after.capped {
        return Some(Change {
            new: Vec::new(),
            gone: Vec::new(),
            new_distinct: 0,
            gone_distinct: 0,
            shared_distinct: 0,
            distinct,
            capped: true,
        });
    }
    let (new, new_distinct) = top(&after.counts, &before.counts);
    let (gone, gone_distinct) = top(&before.counts, &after.counts);
    if new_distinct == 0 && gone_distinct == 0 {
        return None;
    }
    let shared_distinct = distinct.0 - gone_distinct;
    Some(Change { new, gone, new_distinct, gone_distinct, shared_distinct, distinct, capped: false })
}

/// The fingerprints whose text a pass must keep, by template (the index of its cluster) and position.
pub type Wanted = BTreeMap<u32, Vec<(Slot, Vec<u64>)>>;

/// The texts found, by fingerprint, for each position of each template.
pub type Found = BTreeMap<u32, Vec<(Slot, BTreeMap<u64, Vec<u8>>)>>;

/// The text of chosen values, found by a pass that reads the input again (at most `MAX_VALUE_BYTES` bytes each).
#[derive(Clone, Debug)]
pub struct TextCollector {
    wanted: Arc<Wanted>,
    found: Found,
}

impl TextCollector {
    /// A collector that looks for the values in `wanted`.
    pub fn new(wanted: Arc<Wanted>) -> Self {
        TextCollector { wanted, found: BTreeMap::new() }
    }

    /// Keeps the text of the value when it is wanted.
    pub fn add(&mut self, cluster: u32, position: usize, name: &str, value: &[u8]) {
        let Some(slots) = self.wanted.get(&cluster) else { return };
        let Ok(at) =
            slots.binary_search_by(|((at, called), _)| at.cmp(&position).then_with(|| called.as_str().cmp(name)))
        else {
            return;
        };
        let key = fingerprint(value);
        if slots[at].1.contains(&key) {
            let kept = &value[..value.len().min(crate::values::MAX_VALUE_BYTES)];
            let found = slot_of(self.found.entry(cluster).or_default(), position, name);
            found.entry(key).or_insert_with(|| kept.to_vec());
        }
    }

    /// Adds the collector of another part of the input.
    pub fn merge(&mut self, other: TextCollector) {
        for (cluster, slots) in other.found {
            let mine = self.found.entry(cluster).or_default();
            for ((position, name), texts) in slots {
                let found = slot_of(mine, position, &name);
                for (key, text) in texts {
                    found.entry(key).or_insert(text);
                }
            }
        }
    }

    /// The texts found, by template and position, then by fingerprint.
    pub fn into_found(self) -> Found {
        self.found
    }
}
