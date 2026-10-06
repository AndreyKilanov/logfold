//! Sets of words shared by the matchers that compare templates by the words they contain.

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
pub(super) struct Sets {
    ranks: Vec<u32>,
    start: Vec<u32>,
}

impl Sets {
    /// Number of sets.
    pub(super) fn len(&self) -> usize {
        self.start.len() - 1
    }

    /// The sorted ranks of set `index`.
    pub(super) fn get(&self, index: usize) -> &[u32] {
        &self.ranks[self.start[index] as usize..self.start[index + 1] as usize]
    }
}

/// The templates of both runs as sets of word ranks.
///
/// Rank 0 is the rarest word of both runs, ties go to the code point order. Comparing integers instead of strings makes
/// the verification of a candidate pair a merge of two short integer lists, and the rank order is also the order in
/// which the prefixes are taken.
pub(super) struct Interned {
    pub(super) before: Sets,
    pub(super) after: Sets,
    /// For every rank, the number of templates of both runs that contain the word.
    pub(super) frequency: Vec<u32>,
}

/// Splits the templates into sets of words and ranks the words.
pub(super) fn intern(before: &[&str], after: &[&str]) -> Interned {
    let before_words: Vec<Vec<&str>> = before.iter().map(|text| words(text)).collect();
    let after_words: Vec<Vec<&str>> = after.iter().map(|text| words(text)).collect();
    let mut count: HashMap<&str, u32, RandomState> = HashMap::default();
    for set in before_words.iter().chain(&after_words) {
        for word in set {
            *count.entry(word).or_default() += 1;
        }
    }
    let mut by_frequency: Vec<(&str, u32)> = count.into_iter().collect();
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
    Interned {
        before: convert(&before_words),
        after: convert(&after_words),
        frequency: by_frequency.iter().map(|&(_, frequency)| frequency).collect(),
    }
}

/// The number of shared ranks, or `None` as soon as the sets cannot share `needed` of them.
///
/// `needed` must not exceed the number of shared ranks the caller requires; the merge then stops early without changing
/// any result, and the count of a pair that is not stopped is exact.
pub(super) fn shared_if_reachable(left: &[u32], right: &[u32], needed: usize) -> Option<usize> {
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
    Some(shared)
}

/// Takes the pairs from the highest score, then the lowest before index, then the lowest after index, each template at
/// most once. Returns the pairs sorted by before index.
pub(super) fn take_best(mut candidates: Vec<(f64, u32, u32)>, before: usize, after: usize) -> Vec<(usize, usize)> {
    candidates.sort_by(|a, b| b.0.total_cmp(&a.0).then(a.1.cmp(&b.1)).then(a.2.cmp(&b.2)));
    let mut used_before = vec![false; before];
    let mut used_after = vec![false; after];
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
