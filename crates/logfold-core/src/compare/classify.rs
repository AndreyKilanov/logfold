//! Classification of the templates of two runs: new, disappeared, changed and unchanged (`docs/ALGORITHM.md` §11).

use std::collections::HashMap;

use ahash::RandomState;

use super::{jaccard_pairs, token_subset_pairs};

/// The matcher that pairs the templates that exist in one run only.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum Matcher {
    /// Pairs nothing: a template is the same only when its text is the same.
    Exact,
    /// See [`token_subset_pairs`].
    TokenSubset,
    /// See [`jaccard_pairs`], with this threshold.
    Jaccard(f64),
}

/// When a template is reported.
#[derive(Clone, Copy, Debug)]
pub struct Thresholds {
    /// Minimum factor by which a share must change to be reported as changed.
    pub ratio: f64,
    /// Minimum records, in either run, for a template to be reported as changed.
    pub min_count: u64,
    /// Minimum records for a template to be reported as new or disappeared.
    pub min_new_count: u64,
}

/// The templates of one run as parallel columns; `texts` and `counts` must have the same length.
#[derive(Clone, Copy, Debug)]
pub struct Side<'a> {
    /// Template texts.
    pub texts: &'a [&'a str],
    /// Record counts; a template with a count of zero is not part of the run.
    pub counts: &'a [u64],
    /// Records of the run, the denominator of the shares.
    pub total: u64,
}

/// A template present in both runs whose share changed significantly.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Changed {
    /// Index in the first run.
    pub before: usize,
    /// Index in the second run.
    pub after: usize,
    /// Share of the first run's records.
    pub before_share: f64,
    /// Share of the second run's records.
    pub after_share: f64,
    /// `after_share / before_share`, when both counts are positive and the first share is.
    pub ratio: Option<f64>,
}

/// The result of [`compare_runs`]; every index refers to the columns that were passed in.
#[derive(Clone, Debug, PartialEq)]
pub struct Comparison {
    /// Templates of the second run only, most frequent first.
    pub new: Vec<usize>,
    /// Templates of the first run only, most frequent first.
    pub disappeared: Vec<usize>,
    /// Templates present in both runs, the largest change first.
    pub changed: Vec<Changed>,
    /// Number of templates present in both runs without a significant change.
    pub unchanged: usize,
}

fn share(count: u64, total: u64) -> f64 {
    if total == 0 { 0.0 } else { count as f64 / total as f64 }
}

/// `ratio or 1.0` as the reference implementation spells it: a missing or zero ratio counts as no change.
fn change_factor(ratio: Option<f64>) -> f64 {
    let ratio = match ratio {
        Some(value) if value != 0.0 => value,
        _ => 1.0,
    };
    ratio.max(1.0 / ratio)
}

/// Splits the templates into new, disappeared, changed and unchanged.
///
/// Templates are joined by text. Those present in one run only are offered to `matcher`; every pair it returns is
/// compared as one template, with the text and the statistics of the second run. A template is changed when the larger
/// of its counts reaches `min_count` and its share moved by at least `ratio` (up or down). New and disappeared
/// templates need `min_new_count` records. Each list is sorted most significant first, ties by the template text of the
/// second run (of the first run for disappeared ones).
pub fn compare_runs(before: &Side<'_>, after: &Side<'_>, thresholds: &Thresholds, matcher: Matcher) -> Comparison {
    let live = |side: &Side<'_>| -> Vec<usize> { (0..side.texts.len()).filter(|&i| side.counts[i] > 0).collect() };
    let before_live = live(before);
    let after_live = live(after);
    let after_by_text: HashMap<&str, usize, RandomState> = after_live.iter().map(|&j| (after.texts[j], j)).collect();

    let mut both: Vec<(usize, usize)> = Vec::new();
    let mut before_only: Vec<usize> = Vec::new();
    let mut joined_after = vec![false; after.texts.len()];
    for &i in &before_live {
        match after_by_text.get(before.texts[i]) {
            Some(&j) => {
                both.push((i, j));
                joined_after[j] = true;
            }
            None => before_only.push(i),
        }
    }
    let after_only: Vec<usize> = after_live.iter().copied().filter(|&j| !joined_after[j]).collect();

    let mut paired_before = vec![false; before.texts.len()];
    let mut paired_after = vec![false; after.texts.len()];
    if !before_only.is_empty() && !after_only.is_empty() {
        let before_texts: Vec<&str> = before_only.iter().map(|&i| before.texts[i]).collect();
        let after_texts: Vec<&str> = after_only.iter().map(|&j| after.texts[j]).collect();
        let pairs = match matcher {
            Matcher::Exact => Vec::new(),
            Matcher::TokenSubset => token_subset_pairs(&before_texts, &after_texts),
            Matcher::Jaccard(threshold) => jaccard_pairs(&before_texts, &after_texts, threshold),
        };
        for (bi, aj) in pairs {
            let (i, j) = (before_only[bi], after_only[aj]);
            both.push((i, j));
            paired_before[i] = true;
            paired_after[j] = true;
        }
    }

    let mut changed: Vec<(Changed, f64, u64)> = Vec::new();
    let mut unchanged = 0;
    for (i, j) in both {
        let (before_count, after_count) = (before.counts[i], after.counts[j]);
        let (before_share, after_share) = (share(before_count, before.total), share(after_count, after.total));
        let ratio = (before_count > 0 && after_count > 0 && before_share > 0.0).then(|| after_share / before_share);
        let factor = change_factor(ratio);
        let largest = before_count.max(after_count);
        if largest >= thresholds.min_count && factor >= thresholds.ratio {
            changed.push((Changed { before: i, after: j, before_share, after_share, ratio }, factor, largest));
        } else {
            unchanged += 1;
        }
    }
    changed.sort_by(|a, b| {
        b.1.total_cmp(&a.1).then(b.2.cmp(&a.2)).then_with(|| after.texts[a.0.after].cmp(after.texts[b.0.after]))
    });

    let mut new: Vec<usize> =
        after_only.into_iter().filter(|&j| !paired_after[j] && after.counts[j] >= thresholds.min_new_count).collect();
    new.sort_by(|&a, &b| after.counts[b].cmp(&after.counts[a]).then_with(|| after.texts[a].cmp(after.texts[b])));
    let mut disappeared: Vec<usize> = before_only
        .into_iter()
        .filter(|&i| !paired_before[i] && before.counts[i] >= thresholds.min_new_count)
        .collect();
    disappeared
        .sort_by(|&a, &b| before.counts[b].cmp(&before.counts[a]).then_with(|| before.texts[a].cmp(before.texts[b])));

    Comparison { new, disappeared, changed: changed.into_iter().map(|(entry, _, _)| entry).collect(), unchanged }
}
