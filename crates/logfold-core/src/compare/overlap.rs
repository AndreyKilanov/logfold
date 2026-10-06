//! The `overlap` matcher: pairs templates when one contains most of the words of the other.

use super::sets::{Sets, intern, shared_if_reachable, take_best};

/// A template with fewer words is never paired: it is contained in almost any longer one.
pub const MIN_WORDS: usize = 3;

/// The words of the shorter set that a pair needs in common, lowered by an epsilon so that rounding can only make the
/// bound weaker, never stronger.
fn needed(smaller: usize, threshold: f64) -> usize {
    (threshold * smaller as f64 - 1e-9).ceil().max(0.0) as usize
}

/// The score of a pair whose smaller side has `smaller` words, or `None` when it stays below `threshold`.
fn score(left: &[u32], right: &[u32], threshold: f64) -> Option<f64> {
    let smaller = left.len().min(right.len());
    let shared = shared_if_reachable(left, right, needed(smaller, threshold))?;
    let score = shared as f64 / smaller as f64;
    (score >= threshold).then_some(score)
}

/// Every `(score, before index, after index)` whose overlap reaches `threshold`.
///
/// The score is `shared / min(size)`. A pair needs `ceil(t * min)` shared words, so it shares a word among the first
/// `n - ceil(t * n) + 1` words (rarest first) of its smaller side, whichever side that is. A template of the second run
/// therefore probes its own prefix against all words of the templates of the first run that are not shorter, and all of
/// its words against the prefixes of the shorter ones (the lists are kept longest first, so each probe stops where the
/// sizes stop fitting); the union of both finds every pair. A threshold of zero or less scores every pair.
fn scored(before: &Sets, after: &Sets, vocabulary: usize, threshold: f64) -> Vec<(f64, u32, u32)> {
    let mut found = Vec::new();
    let eligible = |set: &[u32]| set.len() >= MIN_WORDS;
    if threshold <= 0.0 {
        for i in (0..before.len()).filter(|&i| eligible(before.get(i))) {
            for j in (0..after.len()).filter(|&j| eligible(after.get(j))) {
                let (left, right) = (before.get(i), after.get(j));
                let smaller = left.len().min(right.len());
                let shared = shared_if_reachable(left, right, 0).unwrap_or(0);
                found.push((shared as f64 / smaller as f64, i as u32, j as u32));
            }
        }
        return found;
    }
    let prefix_length = |size: usize| -> usize {
        let keep = size as i64 - (threshold * size as f64 - 1e-9).ceil() as i64 + 1;
        keep.clamp(1, size as i64) as usize
    };
    let mut everywhere: Vec<Vec<u32>> = vec![Vec::new(); vocabulary];
    let mut leading: Vec<Vec<u32>> = vec![Vec::new(); vocabulary];
    let mut order: Vec<usize> = (0..before.len()).filter(|&i| eligible(before.get(i))).collect();
    order.sort_by(|&a, &b| before.get(b).len().cmp(&before.get(a).len()).then(a.cmp(&b)));
    for i in order {
        let set = before.get(i);
        let keep = prefix_length(set.len());
        for (position, &word) in set.iter().enumerate() {
            everywhere[word as usize].push(i as u32);
            if position < keep {
                leading[word as usize].push(i as u32);
            }
        }
    }
    let mut seen = vec![u32::MAX; before.len()];
    for j in 0..after.len() {
        let right = after.get(j);
        if !eligible(right) {
            continue;
        }
        let keep = prefix_length(right.len());
        let size = |i: &u32| before.get(*i as usize).len();
        let longer_or_equal = right[..keep]
            .iter()
            .flat_map(|&word| everywhere[word as usize].iter().take_while(|i| size(i) >= right.len()));
        let shorter =
            right.iter().flat_map(|&word| leading[word as usize].iter().rev().take_while(|i| size(i) < right.len()));
        for &i in longer_or_equal.chain(shorter) {
            if seen[i as usize] == j as u32 {
                continue;
            }
            seen[i as usize] = j as u32;
            if let Some(value) = score(before.get(i as usize), right, threshold) {
                found.push((value, i, j as u32));
            }
        }
    }
    found
}

/// Pairs templates by `shared words / words of the shorter one`, best pairs first; each template is used at most once.
///
/// Pairs of templates with at least [`MIN_WORDS`] words each are scored, those below `threshold` are dropped, the rest are
/// taken from the highest score, then the lowest before index, then the lowest after index. Returns the pairs sorted by
/// before index.
pub fn overlap_pairs(before: &[&str], after: &[&str], threshold: f64) -> Vec<(usize, usize)> {
    let interned = intern(before, after);
    let candidates = scored(&interned.before, &interned.after, interned.frequency.len(), threshold);
    take_best(candidates, before.len(), after.len())
}
