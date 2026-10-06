//! The `jaccard` matcher: pairs templates whose sets of words overlap by at least a threshold.

use std::cmp::Ordering;

use super::sets::{Sets, intern, take_best};

fn similarity(left: &[u32], right: &[u32]) -> f64 {
    let (mut a, mut b, mut shared) = (0, 0, 0usize);
    while a < left.len() && b < right.len() {
        match left[a].cmp(&right[b]) {
            Ordering::Less => a += 1,
            Ordering::Greater => b += 1,
            Ordering::Equal => {
                shared += 1;
                a += 1;
                b += 1;
            }
        }
    }
    let union = left.len() + right.len() - shared;
    if union == 0 { 0.0 } else { shared as f64 / union as f64 }
}

/// The score of a pair, or `None` as soon as the sets cannot share `needed` words.
///
/// `needed` must not exceed the number of shared words a pair needs to reach the threshold; the merge then stops early
/// without changing any result, and the score of a pair that is not stopped is computed as in [`similarity`].
fn similarity_if_reachable(left: &[u32], right: &[u32], needed: usize) -> Option<f64> {
    let (mut a, mut b, mut shared) = (0, 0, 0usize);
    while a < left.len() && b < right.len() {
        if shared + (left.len() - a).min(right.len() - b) < needed {
            return None;
        }
        match left[a].cmp(&right[b]) {
            Ordering::Less => a += 1,
            Ordering::Greater => b += 1,
            Ordering::Equal => {
                shared += 1;
                a += 1;
                b += 1;
            }
        }
    }
    let union = left.len() + right.len() - shared;
    Some(if union == 0 { 0.0 } else { shared as f64 / union as f64 })
}

/// A lower bound of the shared words two sets of these sizes need: `shared / (left + right - shared) >= threshold`
/// means `shared >= threshold * (left + right) / (1 + threshold)`. The bound is lowered by a small epsilon so that
/// rounding can only make it weaker, never stronger.
fn needed_overlap(left: usize, right: usize, threshold: f64) -> usize {
    let bound = threshold * (left + right) as f64 / (1.0 + threshold) - 1e-9;
    bound.ceil().max(0.0) as usize
}

/// Whether sets of these sizes can reach `threshold` at all: the score never exceeds `smaller / larger`.
///
/// Both sides are correctly rounded divisions, so a score below `threshold` follows from a bound below it.
fn sizes_allow(left: usize, right: usize, threshold: f64) -> bool {
    let (smaller, larger) = if left < right { (left, right) } else { (right, left) };
    larger > 0 && smaller as f64 / larger as f64 >= threshold
}

/// Every `(score, before index, after index)` whose similarity reaches `threshold`.
///
/// Two sets with similarity `t` share a word among the first `n - ceil(t * n) + 1` words of each, when the words are
/// ordered from the rarest to the most common, so only templates that share such a word are scored, and of those only
/// the ones whose sizes allow the score. A threshold of zero or less scores every pair.
fn scored(before: &Sets, after: &Sets, vocabulary: usize, threshold: f64) -> Vec<(f64, u32, u32)> {
    let mut found = Vec::new();
    if threshold <= 0.0 {
        for i in 0..before.len() {
            for j in 0..after.len() {
                found.push((similarity(before.get(i), after.get(j)), i as u32, j as u32));
            }
        }
        return found;
    }
    let prefix_length = |size: usize| -> usize {
        let keep = size as i64 - (threshold * size as f64 - 1e-9).ceil() as i64 + 1;
        keep.clamp(0, size as i64).max(i64::from(size > 0)) as usize
    };
    let mut index: Vec<Vec<u32>> = vec![Vec::new(); vocabulary];
    for i in 0..before.len() {
        let set = before.get(i);
        for &word in &set[..prefix_length(set.len())] {
            index[word as usize].push(i as u32);
        }
    }
    let mut seen = vec![u32::MAX; before.len()];
    for j in 0..after.len() {
        let right = after.get(j);
        for &word in &right[..prefix_length(right.len())] {
            for &i in &index[word as usize] {
                if seen[i as usize] == j as u32 {
                    continue;
                }
                seen[i as usize] = j as u32;
                let left = before.get(i as usize);
                if !sizes_allow(left.len(), right.len(), threshold) {
                    continue;
                }
                let needed = needed_overlap(left.len(), right.len(), threshold);
                if let Some(score) = similarity_if_reachable(left, right, needed)
                    && score >= threshold
                {
                    found.push((score, i, j as u32));
                }
            }
        }
    }
    found
}

/// Pairs templates by the overlap of their words, best pairs first; each template is used at most once.
///
/// Pairs are scored with the Jaccard similarity of the sets of words, those below `threshold` are dropped, the rest are
/// taken from the highest score, then the lowest before index, then the lowest after index. Returns the pairs sorted by
/// before index.
pub fn jaccard_pairs(before: &[&str], after: &[&str], threshold: f64) -> Vec<(usize, usize)> {
    let interned = intern(before, after);
    let candidates = scored(&interned.before, &interned.after, interned.frequency.len(), threshold);
    take_best(candidates, before.len(), after.len())
}
