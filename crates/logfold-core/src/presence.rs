//! Which values a variable position took in each run, to tell the new ones from the gone ones (ADR-018).
//!
//! A value is kept as a 64-bit fingerprint with the number of records that gave it and its text (cut at
//! [`MAX_VALUE_BYTES`] bytes, stored in one buffer): about 30 bytes for a short value and at most 90 for a long one. The
//! memory is bounded: a position keeps at most [`MAX_PER_POSITION`] different values and a collector at most `limit` in all
//! positions. A position that went over a limit is marked `capped`, gives no lists and keeps nothing but the number of
//! values it had counted, because with part of the values missing a value that looks new may only be one that was not
//! counted. When the collector is full it caps its largest position, not the one that asks for room: a position that
//! gets a new value on almost every record (a request id) must not starve the positions that can be compared. Sums and
//! unions do not depend on their order, so without a cap the result is the same for any number of threads and any size
//! of chunk.

use std::collections::{BTreeMap, HashMap};
use std::hash::{BuildHasherDefault, DefaultHasher, Hasher};

use crate::values::{MAX_VALUE_BYTES, Slot, slot_of};

/// The number of different values that a position keeps for one run.
pub const MAX_PER_POSITION: usize = 1_000_000;
/// The number of different values that the collector of a run keeps in all positions.
pub const MAX_PER_RUN: usize = 4_000_000;
/// The number of different values that the collector of one chunk keeps in all positions.
pub const MAX_PER_CHUNK: usize = 1_000_000;
/// The number of new values, and of gone ones, that a position lists.
pub const TOP_CHANGES: usize = 10;

/// The buffer of texts is addressed by `u32` offsets: a position must not be able to outgrow them.
const _: () = assert!(MAX_PER_POSITION * (MAX_VALUE_BYTES + 1) < u32::MAX as usize);

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

/// The 64-bit fingerprint of a value (SipHash-1-3 with a zero key, whole value).
pub fn fingerprint(value: &[u8]) -> u64 {
    let mut hasher = DefaultHasher::new();
    hasher.write(value);
    hasher.finish()
}

/// The records that gave a value and where its text is in the buffer of the set.
#[derive(Clone, Copy, Debug)]
struct Entry {
    count: u32,
    offset: u32,
}

/// The values of one position in one run: for each fingerprint, the records that gave it and the text.
#[derive(Clone, Debug, Default)]
pub struct ValueSet {
    entries: HashMap<u64, Entry, BuildHasherDefault<Identity>>,
    texts: Vec<u8>,
    capped: bool,
    floor: usize,
}

impl ValueSet {
    /// The number of different values held (none once the set is capped).
    pub fn len(&self) -> usize {
        self.entries.len()
    }

    /// Whether no value is held.
    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    /// Whether a limit was hit, so that some values are missing.
    pub fn capped(&self) -> bool {
        self.capped
    }

    /// The number of different values counted: exact unless the set is capped, then a lower bound.
    pub fn distinct(&self) -> usize {
        self.floor.max(self.entries.len())
    }

    fn text(&self, entry: Entry) -> &[u8] {
        let start = entry.offset as usize;
        let length = usize::from(self.texts[start]);
        &self.texts[start + 1..start + 1 + length]
    }

    /// Gives up the values and marks the set as capped; the number of values counted so far is remembered.
    fn cap(&mut self, known: usize) {
        self.floor = self.distinct().max(known);
        self.entries = HashMap::default();
        self.texts = Vec::new();
        self.capped = true;
    }

    /// Adds `count` records of the value with `key` and `text` (already cut). A value that is new to a capped set is
    /// ignored; one that does not fit (`room` is false, or the position is full) caps the set.
    fn add(&mut self, key: u64, text: &[u8], count: u32, room: bool) {
        if let Some(seen) = self.entries.get_mut(&key) {
            seen.count = seen.count.saturating_add(count);
        } else if !self.capped {
            if room && self.entries.len() < MAX_PER_POSITION {
                let offset = self.texts.len() as u32;
                self.texts.push(text.len() as u8);
                self.texts.extend_from_slice(text);
                self.entries.insert(key, Entry { count, offset });
            } else {
                self.cap(self.entries.len());
            }
        }
    }

    /// Adds the values of `other`, as far as the limit of a position allows.
    pub fn merge(&mut self, other: &ValueSet) {
        if self.capped || other.capped {
            self.cap(other.distinct());
            return;
        }
        for (&key, &entry) in &other.entries {
            self.add(key, other.text(entry), entry.count, true);
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
        let text = &value[..value.len().min(MAX_VALUE_BYTES)];
        self.add_entry(cluster, position, name, fingerprint(value), text, 1);
    }

    /// Whether the position keeps the value already, or keeps nothing any more (it is capped).
    fn settled(&self, cluster: u32, position: usize, name: &str, key: u64) -> bool {
        let Some(slots) = self.clusters.get(&cluster) else { return false };
        let found =
            slots.binary_search_by(|((at, called), _)| at.cmp(&position).then_with(|| called.as_str().cmp(name)));
        found.is_ok_and(|index| slots[index].1.capped || slots[index].1.entries.contains_key(&key))
    }

    /// Caps the position that holds the most values, to make room; returns whether it made any.
    fn shed(&mut self) -> bool {
        let mut largest: Option<&mut ValueSet> = None;
        for set in self.clusters.values_mut().flat_map(|slots| slots.iter_mut().map(|(_, set)| set)) {
            if set.len() > largest.as_ref().map_or(0, |best| best.len()) {
                largest = Some(set);
            }
        }
        let Some(set) = largest else { return false };
        self.total -= set.len();
        set.cap(0);
        true
    }

    fn add_entry(&mut self, cluster: u32, position: usize, name: &str, key: u64, text: &[u8], count: u32) {
        if self.total >= self.limit && !self.settled(cluster, position, name, key) {
            self.shed();
        }
        let room = self.total < self.limit;
        let set = slot_of(self.clusters.entry(cluster).or_default(), position, name);
        let before = set.len();
        set.add(key, text, count, room);
        self.total = self.total - before + set.len();
    }

    /// Adds the collector of another part of the input.
    pub fn merge(&mut self, other: PresenceCollector) {
        for (cluster, slots) in other.clusters {
            for ((position, name), theirs) in slots {
                if theirs.capped {
                    let set = slot_of(self.clusters.entry(cluster).or_default(), position, &name);
                    let before = set.len();
                    set.cap(theirs.distinct());
                    self.total -= before;
                    continue;
                }
                for (&key, &entry) in &theirs.entries {
                    self.add_entry(cluster, position, &name, key, theirs.text(entry), entry.count);
                }
            }
        }
    }

    /// The sets by template and position, in order.
    pub fn into_clusters(self) -> BTreeMap<u32, Vec<(Slot, ValueSet)>> {
        self.clusters
    }
}

/// How the values of one position differ between two runs.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Change {
    /// The most frequent values of the second run that the first run lacks: `(text, records)`, by records (more first)
    /// and then by text.
    pub new: Vec<(Vec<u8>, u64)>,
    /// The most frequent values of the first run that the second run lacks.
    pub gone: Vec<(Vec<u8>, u64)>,
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

type Listed<'a> = Vec<(&'a [u8], u64)>;

/// The values of `values` that `other` lacks, the most frequent first, and how many there are.
fn top<'a>(values: &'a ValueSet, other: &ValueSet) -> (Listed<'a>, u64) {
    let mut only: Listed<'a> = values
        .entries
        .iter()
        .filter(|(key, _)| !other.entries.contains_key(key))
        .map(|(_, &entry)| (values.text(entry), u64::from(entry.count)))
        .collect();
    let total = only.len() as u64;
    let order = |a: &(&[u8], u64), b: &(&[u8], u64)| b.1.cmp(&a.1).then_with(|| a.0.cmp(b.0));
    if only.len() > TOP_CHANGES {
        only.select_nth_unstable_by(TOP_CHANGES - 1, order);
        only.truncate(TOP_CHANGES);
    }
    only.sort_by(order);
    (only, total)
}

fn owned(values: Listed<'_>) -> Vec<(Vec<u8>, u64)> {
    values.into_iter().map(|(text, count)| (text.to_vec(), count)).collect()
}

/// Compares the values of one position in the first and the second run; `None` when they are the same set.
pub fn compare(before: &ValueSet, after: &ValueSet) -> Option<Change> {
    let distinct = (before.distinct() as u64, after.distinct() as u64);
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
    let (new, new_distinct) = top(after, before);
    let (gone, gone_distinct) = top(before, after);
    if new_distinct == 0 && gone_distinct == 0 {
        return None;
    }
    let shared_distinct = distinct.0 - gone_distinct;
    Some(Change {
        new: owned(new),
        gone: owned(gone),
        new_distinct,
        gone_distinct,
        shared_distinct,
        distinct,
        capped: false,
    })
}
