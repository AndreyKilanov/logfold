use crate::level::LEVEL_COUNT;

/// Statistics of one cluster within one run.
#[derive(Clone, Debug)]
pub struct RunStats {
    /// Number of records.
    pub count: u64,
    /// Smallest timestamp (microseconds) seen, `i64::MAX` when none.
    pub first: i64,
    /// Largest timestamp (microseconds) seen, `i64::MIN` when none.
    pub last: i64,
    /// Record counts per known level, indexed by level rank.
    pub levels: [u64; LEVEL_COUNT],
    /// Raw message of the first record of this run.
    pub example: Option<Box<[u8]>>,
}

impl Default for RunStats {
    fn default() -> Self {
        RunStats { count: 0, first: i64::MAX, last: i64::MIN, levels: [0; LEVEL_COUNT], example: None }
    }
}

impl RunStats {
    /// Returns true when at least one record carried a timestamp.
    pub fn has_time(&self) -> bool {
        self.first <= self.last
    }

    /// Absorbs another statistics block; the example of `self` wins when present.
    pub fn absorb(&mut self, other: &RunStats) {
        self.count += other.count;
        self.first = self.first.min(other.first);
        self.last = self.last.max(other.last);
        for (dst, src) in self.levels.iter_mut().zip(other.levels.iter()) {
            *dst += src;
        }
        if self.example.is_none() {
            self.example = other.example.clone();
        }
    }
}
