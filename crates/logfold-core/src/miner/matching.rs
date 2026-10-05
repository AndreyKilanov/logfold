//! Token access and scoring helpers shared by the template tree.

use crate::stats::RunStats;
use crate::tokenizer::TokenView;

use super::{RecordMeta, MAX_EXAMPLE_BYTES, WILDCARD};

pub(super) trait Tokens {
    fn count(&self) -> usize;
    fn at(&self, index: usize) -> &[u8];
}

impl Tokens for TokenView<'_> {
    fn count(&self) -> usize {
        self.len()
    }
    fn at(&self, index: usize) -> &[u8] {
        self.get(index)
    }
}

pub(super) struct BoxedTokens<'a>(pub(super) &'a [Box<[u8]>]);

impl Tokens for BoxedTokens<'_> {
    fn count(&self) -> usize {
        self.0.len()
    }
    fn at(&self, index: usize) -> &[u8] {
        &self.0[index]
    }
}

pub(super) fn has_digit(token: &[u8]) -> bool {
    token.iter().any(u8::is_ascii_digit)
}

fn truncate_example(message: &[u8]) -> Box<[u8]> {
    let text = String::from_utf8_lossy(message);
    let mut end = text.len().min(MAX_EXAMPLE_BYTES);
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    Box::from(text[..end].as_bytes())
}

pub(crate) fn update_stats(stats: &mut RunStats, rec: &RecordMeta<'_>) {
    stats.count += 1;
    if let Some(ts) = rec.timestamp {
        stats.first = stats.first.min(ts);
        stats.last = stats.last.max(ts);
    }
    if let Some(level) = rec.level {
        stats.levels[level.rank()] += 1;
    }
    if stats.example.is_none() {
        stats.example = Some(truncate_example(rec.message));
    }
}

/// Scores `template` against `tokens`; gives up (`None`) as soon as the exact matches cannot reach `floor`.
pub(super) fn score_bounded<T: Tokens>(template: &[Box<[u8]>], tokens: &T, floor: usize) -> Option<(usize, usize)> {
    let n = template.len();
    let mut exact = 0;
    let mut params = 0;
    for (index, token) in template.iter().enumerate() {
        if &**token == WILDCARD {
            params += 1;
        } else if &**token == tokens.at(index) {
            exact += 1;
        }
        if exact + (n - index - 1) < floor {
            return None;
        }
    }
    (exact >= floor).then_some((exact, params))
}
