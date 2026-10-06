//! The `jaccard_idf` matcher: Jaccard similarity of the sets of words, where a rare word counts more than a common one.

use std::cmp::Ordering;

use super::sets::{Sets, intern, take_best};

/// Relative slack of the filters, so that rounding can only make a filter weaker, never stronger.
const SLACK: f64 = 1e-9;

/// Words and their weights, as ranks (rarest first) and `1 / frequency` per rank.
struct Weighted<'a> {
    sets: &'a Sets,
    weight: &'a [f64],
}

impl Weighted<'_> {
    /// The total weight of set `index`, summed in rank order.
    fn total(&self, index: usize) -> f64 {
        let mut total = 0.0;
        for &rank in self.sets.get(index) {
            total += self.weight[rank as usize];
        }
        total
    }
}

/// The weighted Jaccard score: shared weight over the weight of the union, both summed in rank order.
fn similarity(weight: &[f64], left: &[u32], right: &[u32]) -> f64 {
    let (mut a, mut b) = (0, 0);
    let (mut shared, mut union) = (0.0f64, 0.0f64);
    while a < left.len() && b < right.len() {
        match left[a].cmp(&right[b]) {
            Ordering::Less => {
                union += weight[left[a] as usize];
                a += 1;
            }
            Ordering::Greater => {
                union += weight[right[b] as usize];
                b += 1;
            }
            Ordering::Equal => {
                let both = weight[left[a] as usize];
                shared += both;
                union += both;
                a += 1;
                b += 1;
            }
        }
    }
    for &rank in &left[a..] {
        union += weight[rank as usize];
    }
    for &rank in &right[b..] {
        union += weight[rank as usize];
    }
    if union <= 0.0 { 0.0 } else { shared / union }
}

/// The number of leading words (heaviest first) that a set must probe.
///
/// Two sets with a score of at least `t` share their heaviest common word `x`; the words of `A` from `x` on weigh at
/// least `t * weight(A)`, so `x` lies among the leading words of `A` whose suffix still weighs that much. The same holds
/// for the other set.
fn prefix_length(weight: &[f64], set: &[u32], total: f64, threshold: f64) -> usize {
    let bound = threshold * total * (1.0 - SLACK);
    let mut suffix = 0.0;
    for (position, &rank) in set.iter().enumerate().rev() {
        suffix += weight[rank as usize];
        if suffix >= bound {
            return position + 1;
        }
    }
    0
}

/// Whether sets of these weights can reach `threshold`: the score never exceeds `smaller / larger`.
fn weights_allow(left: f64, right: f64, threshold: f64) -> bool {
    let (smaller, larger) = if left < right { (left, right) } else { (right, left) };
    larger > 0.0 && smaller >= larger * threshold * (1.0 - SLACK)
}

/// Every `(score, before index, after index)` whose weighted similarity reaches `threshold`.
///
/// Only templates that share a word among their leading words (see [`prefix_length`]) are scored, and of those only the
/// ones whose weights allow the score. A threshold of zero or less scores every pair.
fn scored(before: &Weighted<'_>, after: &Weighted<'_>, threshold: f64) -> Vec<(f64, u32, u32)> {
    let mut found = Vec::new();
    let weight = before.weight;
    if threshold <= 0.0 {
        for i in 0..before.sets.len() {
            for j in 0..after.sets.len() {
                found.push((similarity(weight, before.sets.get(i), after.sets.get(j)), i as u32, j as u32));
            }
        }
        return found;
    }
    let before_total: Vec<f64> = (0..before.sets.len()).map(|i| before.total(i)).collect();
    let mut index: Vec<Vec<u32>> = vec![Vec::new(); weight.len()];
    for i in 0..before.sets.len() {
        let set = before.sets.get(i);
        for &rank in &set[..prefix_length(weight, set, before_total[i], threshold)] {
            index[rank as usize].push(i as u32);
        }
    }
    let mut seen = vec![u32::MAX; before.sets.len()];
    for j in 0..after.sets.len() {
        let right = after.sets.get(j);
        let right_total = after.total(j);
        for &rank in &right[..prefix_length(weight, right, right_total, threshold)] {
            for &i in &index[rank as usize] {
                if seen[i as usize] == j as u32 {
                    continue;
                }
                seen[i as usize] = j as u32;
                if !weights_allow(before_total[i as usize], right_total, threshold) {
                    continue;
                }
                let score = similarity(weight, before.sets.get(i as usize), right);
                if score >= threshold {
                    found.push((score, i, j as u32));
                }
            }
        }
    }
    found
}

/// Pairs templates by the weighted overlap of their words, best pairs first; each template is used at most once.
///
/// A word weighs `1 / n`, where `n` is the number of templates of both runs (the ones handed to the matcher) that contain
/// it. The score of two templates is the weight of the words they share over the weight of all their words (0 when
/// both are empty). Pairs below `threshold` are dropped, the rest are taken from the highest score, then the lowest
/// before index, then the lowest after index. Returns the pairs sorted by before index.
pub fn jaccard_idf_pairs(before: &[&str], after: &[&str], threshold: f64) -> Vec<(usize, usize)> {
    let interned = intern(before, after);
    let weight: Vec<f64> = interned.frequency.iter().map(|&frequency| 1.0 / f64::from(frequency)).collect();
    let left = Weighted { sets: &interned.before, weight: &weight };
    let right = Weighted { sets: &interned.after, weight: &weight };
    take_best(scored(&left, &right, threshold), before.len(), after.len())
}
