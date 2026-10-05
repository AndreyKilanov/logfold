//! The `jaccard` matcher: pairs templates whose sets of words overlap by at least a threshold.

use std::cmp::Ordering;
use std::collections::HashMap;

use ahash::RandomState;

/// Whitespace as Python's `str.split()` sees it: the Unicode `White_Space` set plus the separators U+001C to U+001F.
fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// The distinct words of a template, sorted.
fn words(text: &str) -> Vec<&str> {
    let mut words: Vec<&str> = text.split(is_space).filter(|word| !word.is_empty()).collect();
    words.sort_unstable();
    words.dedup();
    words
}

fn similarity(left: &[&str], right: &[&str]) -> f64 {
    let (mut a, mut b, mut shared) = (0, 0, 0usize);
    while a < left.len() && b < right.len() {
        match left[a].cmp(right[b]) {
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

/// The words that must overlap for two sets to reach `threshold`: the rarest `n - ceil(threshold * n) + 1` of them.
fn prefix<'w>(set: &[&'w str], rank: &HashMap<&str, u32, RandomState>, threshold: f64) -> Vec<&'w str> {
    let mut ordered = set.to_vec();
    ordered.sort_unstable_by_key(|word| rank[word]);
    let keep = ordered.len() as i64 - (threshold * ordered.len() as f64 - 1e-9).ceil() as i64 + 1;
    ordered.truncate(keep.max(1) as usize);
    ordered
}

/// Every `(score, before index, after index)` whose similarity reaches `threshold`.
///
/// Two sets with similarity `t` share a word among the first `n - ceil(t * n) + 1` words of each, when the words are
/// ordered from the rarest to the most common, so only templates that share such a word are scored. A threshold of
/// zero or less scores every pair.
fn scored(before: &[Vec<&str>], after: &[Vec<&str>], threshold: f64) -> Vec<(f64, u32, u32)> {
    let mut found = Vec::new();
    if threshold <= 0.0 {
        for (i, left) in before.iter().enumerate() {
            for (j, right) in after.iter().enumerate() {
                found.push((similarity(left, right), i as u32, j as u32));
            }
        }
        return found;
    }
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
    let mut index: HashMap<&str, Vec<u32>, RandomState> = HashMap::default();
    for (i, set) in before.iter().enumerate() {
        for word in prefix(set, &rank, threshold) {
            index.entry(word).or_default().push(i as u32);
        }
    }
    let mut seen = vec![u32::MAX; before.len()];
    for (j, right) in after.iter().enumerate() {
        for word in prefix(right, &rank, threshold) {
            let Some(candidates) = index.get(word) else { continue };
            for &i in candidates {
                if seen[i as usize] == j as u32 {
                    continue;
                }
                seen[i as usize] = j as u32;
                let score = similarity(&before[i as usize], right);
                if score >= threshold {
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
    let before_words: Vec<Vec<&str>> = before.iter().map(|text| words(text)).collect();
    let after_words: Vec<Vec<&str>> = after.iter().map(|text| words(text)).collect();
    let mut candidates = scored(&before_words, &after_words, threshold);
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
