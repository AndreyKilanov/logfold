//! The `jaccard` matcher: pairs templates whose sets of words overlap by at least a threshold.

use std::cmp::Ordering;
use std::collections::HashMap;

use ahash::RandomState;

/// Whitespace as Python's `str.split()` sees it: the Unicode `White_Space` set plus the separators U+001C to U+001F.
fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// The distinct words of a template.
fn words(text: &str) -> Vec<&str> {
    let mut words: Vec<&str> = text.split(is_space).filter(|word| !word.is_empty()).collect();
    words.sort_unstable();
    words.dedup();
    words
}

/// Sets of word ranks stored back to back, which keeps the verification of a candidate pair inside one cache line or two.
struct Sets {
    ranks: Vec<u32>,
    start: Vec<u32>,
}

impl Sets {
    fn len(&self) -> usize {
        self.start.len() - 1
    }

    fn get(&self, index: usize) -> &[u32] {
        &self.ranks[self.start[index] as usize..self.start[index + 1] as usize]
    }
}

/// Sets of words as sorted lists of ranks: rank 0 is the rarest word of both runs, ties go to the code point order.
///
/// Comparing integers instead of strings makes the verification of a candidate pair a merge of two short integer lists,
/// and the sorted order is also the order in which the prefixes are taken.
fn intern(before: &[Vec<&str>], after: &[Vec<&str>]) -> (Sets, Sets, usize) {
    let mut frequency: HashMap<&str, u32, RandomState> = HashMap::default();
    for set in before.iter().chain(after) {
        for word in set {
            *frequency.entry(word).or_default() += 1;
        }
    }
    let mut by_frequency: Vec<(&str, u32)> = frequency.into_iter().collect();
    by_frequency.sort_unstable_by(|a, b| a.1.cmp(&b.1).then(a.0.cmp(b.0)));
    let rank: HashMap<&str, u32, RandomState> =
        by_frequency.iter().enumerate().map(|(position, (word, _))| (*word, position as u32)).collect();
    let convert = |sets: &[Vec<&str>]| -> Sets {
        let mut flat = Sets { ranks: Vec::new(), start: vec![0] };
        for set in sets {
            let first = flat.ranks.len();
            flat.ranks.extend(set.iter().map(|word| rank[word]));
            flat.ranks[first..].sort_unstable();
            flat.start.push(flat.ranks.len() as u32);
        }
        flat
    };
    (convert(before), convert(after), by_frequency.len())
}

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
    if union == 0 {
        0.0
    } else {
        shared as f64 / union as f64
    }
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
                if let Some(score) = similarity_if_reachable(left, right, needed) {
                    if score >= threshold {
                        found.push((score, i, j as u32));
                    }
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
    let before_words: Vec<Vec<&str>> = before.iter().map(|text| words(text)).collect();
    let after_words: Vec<Vec<&str>> = after.iter().map(|text| words(text)).collect();
    let (before_ranks, after_ranks, vocabulary) = intern(&before_words, &after_words);
    let mut candidates = scored(&before_ranks, &after_ranks, vocabulary, threshold);
    candidates.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)).then(a.2.cmp(&b.2)));
    let mut used_before = vec![false; before.len()];
    let mut used_after = vec![false; after.len()];
    let mut pairs = Vec::new();
    for (_, i, j) in candidates {
        if !used_before[i as usize] && !used_after[j as usize] {
            used_before[i as usize] = true;
            used_after[j as usize] = true;
            pairs.push((i as usize, j as usize));
        }
    }
    pairs.sort_unstable();
    pairs
}
