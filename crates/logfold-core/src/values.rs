//! Distributions of the values that the messages of a template give to its variable positions (ADR-016).
//!
//! Everything here has bounded memory and merges deterministically. A position keeps exact counters for at most
//! [`MAX_DISTINCT`] different values (each cut at [`MAX_VALUE_BYTES`] bytes) and counts the others in a single number; the
//! numbers among the values go into fixed logarithmic buckets, which add exactly in any order, so the percentiles do not
//! depend on how the input was cut into chunks. The bucket limits are built with exactly rounded multiplications and
//! divisions only, so they are the same on every platform.

use std::collections::BTreeMap;
use std::sync::OnceLock;

use crate::parameters::Parameter;

/// Longest value that is kept; a longer value is cut (and counted under its first bytes).
pub const MAX_VALUE_BYTES: usize = 64;
/// The number of different values that a position counts exactly; later new values go to `other`.
pub const MAX_DISTINCT: usize = 1000;
/// The number of values that a summary lists.
pub const TOP_VALUES: usize = 10;

const GAMMA: f64 = 1.05;
const MIN_INDEX: i32 = -425;
const MAX_INDEX: i32 = 709;
/// Numbers of at most this size in absolute value are counted as zero.
const SMALLEST: f64 = 1e-9;
const MAX_NUMBER_BYTES: usize = 32;

/// `GAMMA^index` for the indexes from [`MIN_INDEX`] to [`MAX_INDEX`], by repeated exactly rounded operations.
fn limits() -> &'static [f64] {
    static LIMITS: OnceLock<Vec<f64>> = OnceLock::new();
    LIMITS.get_or_init(|| {
        let size = (MAX_INDEX - MIN_INDEX + 1) as usize;
        let mut table = vec![1.0; size];
        let origin = (-MIN_INDEX) as usize;
        for index in origin + 1..size {
            table[index] = table[index - 1] * GAMMA;
        }
        for index in (0..origin).rev() {
            table[index] = table[index + 1] / GAMMA;
        }
        table
    })
}

/// The number that a value is, when it is written as `-?digits(.digits)?`.
fn number(value: &[u8]) -> Option<f64> {
    if value.is_empty() || value.len() > MAX_NUMBER_BYTES {
        return None;
    }
    let digits = value.strip_prefix(b"-").unwrap_or(value);
    let (whole, fraction) = match digits.iter().position(|&byte| byte == b'.') {
        Some(dot) => (&digits[..dot], Some(&digits[dot + 1..])),
        None => (digits, None),
    };
    let all_digits = |text: &[u8]| !text.is_empty() && text.iter().all(u8::is_ascii_digit);
    if !all_digits(whole) || fraction.is_some_and(|text| !all_digits(text)) {
        return None;
    }
    std::str::from_utf8(value).ok()?.parse().ok()
}

/// The numbers of a position in logarithmic buckets of relative width `GAMMA`.
#[derive(Clone, Debug)]
struct Sketch {
    count: u64,
    zero: u64,
    min: f64,
    max: f64,
    sum: f64,
    positive: BTreeMap<i32, u64>,
    negative: BTreeMap<i32, u64>,
}

impl Default for Sketch {
    fn default() -> Self {
        Sketch {
            count: 0,
            zero: 0,
            min: f64::INFINITY,
            max: f64::NEG_INFINITY,
            sum: 0.0,
            positive: BTreeMap::new(),
            negative: BTreeMap::new(),
        }
    }
}

impl Sketch {
    fn add(&mut self, value: f64) {
        self.count += 1;
        self.sum += value;
        self.min = self.min.min(value);
        self.max = self.max.max(value);
        let size = value.abs();
        if size < SMALLEST {
            self.zero += 1;
            return;
        }
        let table = limits();
        let index = table.partition_point(|&limit| limit < size.min(table[table.len() - 1]));
        let bucket = MIN_INDEX + index as i32;
        let buckets = if value > 0.0 { &mut self.positive } else { &mut self.negative };
        *buckets.entry(bucket).or_insert(0) += 1;
    }

    fn merge(&mut self, other: &Sketch) {
        self.count += other.count;
        self.zero += other.zero;
        self.sum += other.sum;
        self.min = self.min.min(other.min);
        self.max = self.max.max(other.max);
        for (bucket, count) in &other.positive {
            *self.positive.entry(*bucket).or_insert(0) += count;
        }
        for (bucket, count) in &other.negative {
            *self.negative.entry(*bucket).or_insert(0) += count;
        }
    }

    /// The middle of a bucket, which is within `(GAMMA - 1) / (GAMMA + 1)` of every number in it.
    fn middle(bucket: i32) -> f64 {
        2.0 * limits()[(bucket - MIN_INDEX) as usize] / (GAMMA + 1.0)
    }

    /// The value of the number with the 0-based rank `floor(q * (count - 1))`, within the relative error of a bucket.
    fn quantile(&self, q: f64) -> f64 {
        let rank = (q * (self.count - 1) as f64).floor() as u64;
        let mut seen = 0;
        for (bucket, count) in self.negative.iter().rev() {
            seen += count;
            if seen > rank {
                return (-Self::middle(*bucket)).clamp(self.min, self.max);
            }
        }
        seen += self.zero;
        if seen > rank {
            return 0.0_f64.clamp(self.min, self.max);
        }
        for (bucket, count) in &self.positive {
            seen += count;
            if seen > rank {
                return Self::middle(*bucket).clamp(self.min, self.max);
            }
        }
        self.max
    }
}

/// The values of one variable position of one template.
#[derive(Clone, Debug, Default)]
pub struct Distribution {
    count: u64,
    values: BTreeMap<Vec<u8>, u64>,
    other: u64,
    numbers: Sketch,
}

/// What a [`Distribution`] says about the numbers among its values.
#[derive(Clone, Debug, PartialEq)]
pub struct NumericSummary {
    /// How many of the values were numbers.
    pub count: u64,
    /// The smallest number.
    pub min: f64,
    /// The largest number.
    pub max: f64,
    /// The mean of the numbers.
    pub mean: f64,
    /// The median, within the error of a bucket (about 2.4%).
    pub p50: f64,
    /// The 90th percentile, within the same error.
    pub p90: f64,
    /// The 99th percentile, within the same error.
    pub p99: f64,
}

/// What a [`Distribution`] says about its values.
#[derive(Clone, Debug, PartialEq)]
pub struct ValueSummary {
    /// How many values were seen.
    pub count: u64,
    /// The most frequent values with their counts, by count (most first) and then by bytes; at most [`TOP_VALUES`].
    pub top: Vec<(Vec<u8>, u64)>,
    /// How many different values are counted exactly (the real number of different values when `capped` is false,
    /// a lower bound otherwise).
    pub distinct: u64,
    /// Whether the counters were full, so that some values were only counted in `other`.
    pub capped: bool,
    /// How many values were not counted one by one.
    pub other: u64,
    /// The numbers among the values, when there were any.
    pub numeric: Option<NumericSummary>,
}

impl Distribution {
    /// Counts one value.
    pub fn add(&mut self, value: &[u8]) {
        self.count += 1;
        if let Some(parsed) = number(value) {
            self.numbers.add(parsed);
        }
        self.count_value(&value[..value.len().min(MAX_VALUE_BYTES)], 1);
    }

    fn count_value(&mut self, key: &[u8], count: u64) {
        if let Some(seen) = self.values.get_mut(key) {
            *seen += count;
        } else if self.values.len() < MAX_DISTINCT {
            self.values.insert(key.to_vec(), count);
        } else {
            self.other += count;
        }
    }

    /// Adds the values of `other`, which come later in the input than the values of `self`.
    pub fn merge(&mut self, other: &Distribution) {
        self.count += other.count;
        self.other += other.other;
        self.numbers.merge(&other.numbers);
        for (key, count) in &other.values {
            self.count_value(key, *count);
        }
    }

    /// Sums the distribution up.
    pub fn summary(&self) -> ValueSummary {
        let mut ranked: Vec<(&Vec<u8>, &u64)> = self.values.iter().collect();
        ranked.sort_by(|a, b| b.1.cmp(a.1).then_with(|| a.0.cmp(b.0)));
        let numbers = &self.numbers;
        let numeric = (numbers.count > 0).then(|| NumericSummary {
            count: numbers.count,
            min: numbers.min,
            max: numbers.max,
            mean: numbers.sum / numbers.count as f64,
            p50: numbers.quantile(0.50),
            p90: numbers.quantile(0.90),
            p99: numbers.quantile(0.99),
        });
        ValueSummary {
            count: self.count,
            top: ranked.into_iter().take(TOP_VALUES).map(|(value, count)| (value.clone(), *count)).collect(),
            distinct: self.values.len() as u64,
            capped: self.other > 0,
            other: self.other,
            numeric,
        }
    }
}

/// The variable position of a template that a distribution belongs to: the index of the token and the name of the
/// parameter (`*` for a generalized position, the name of the masking rule otherwise).
pub type Slot = (usize, String);

/// The distributions of the templates (given by the index of their cluster) of one run.
#[derive(Clone, Debug, Default)]
pub struct ValueCollector {
    clusters: BTreeMap<u32, Vec<(Slot, Distribution)>>,
}

/// Finds the distribution of a position in the few that a template has, or makes it; the list stays sorted by position.
fn slot_of<'a>(slots: &'a mut Vec<(Slot, Distribution)>, position: usize, name: &str) -> &'a mut Distribution {
    let found = slots.binary_search_by(|((at, called), _)| at.cmp(&position).then_with(|| called.as_str().cmp(name)));
    let index = match found {
        Ok(index) => index,
        Err(index) => {
            slots.insert(index, ((position, name.to_string()), Distribution::default()));
            index
        }
    };
    &mut slots[index].1
}

impl ValueCollector {
    /// Counts the values that a message of the template `cluster` gave to its variable positions.
    pub fn add(&mut self, cluster: u32, parameters: &[Parameter]) {
        let slots = self.clusters.entry(cluster).or_default();
        for parameter in parameters {
            slot_of(slots, parameter.position, &parameter.name).add(&parameter.value);
        }
    }

    /// Adds the collector of a later part of the input.
    pub fn merge(&mut self, other: ValueCollector) {
        for (cluster, slots) in other.clusters {
            let mine = self.clusters.entry(cluster).or_default();
            for ((position, name), distribution) in slots {
                slot_of(mine, position, &name).merge(&distribution);
            }
        }
    }

    /// The distributions by cluster and position, in order.
    pub fn into_clusters(self) -> BTreeMap<u32, BTreeMap<Slot, Distribution>> {
        self.clusters.into_iter().map(|(cluster, slots)| (cluster, slots.into_iter().collect())).collect()
    }
}
