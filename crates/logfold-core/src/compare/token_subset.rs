//! The `token_subset` matcher: equal token count, one template generalizes the other position by position.

use std::collections::HashMap;

use ahash::RandomState;

const WILDCARD: &str = "<*>";

fn tokens(text: &str) -> Vec<&str> {
    if text.is_empty() { Vec::new() } else { text.split(' ').collect() }
}

fn wildcards(tokens: &[&str]) -> usize {
    tokens.iter().filter(|token| **token == WILDCARD).count()
}

fn generalizes(general: &[&str], specific: &[&str]) -> bool {
    general.iter().zip(specific).all(|(g, s)| *g == WILDCARD || g == s)
}

/// Templates of one token count, indexed by the literal token or wildcard at every position.
#[derive(Default)]
struct Bucket<'a> {
    members: Vec<u32>,
    exact: Vec<HashMap<&'a str, Vec<u32>, RandomState>>,
    wildcard: Vec<Vec<u32>>,
}

impl<'a> Bucket<'a> {
    fn add(&mut self, index: u32, tokens: &[&'a str]) {
        if self.exact.is_empty() {
            self.exact = tokens.iter().map(|_| HashMap::default()).collect();
            self.wildcard = tokens.iter().map(|_| Vec::new()).collect();
        }
        self.members.push(index);
        for (position, token) in tokens.iter().enumerate() {
            if *token == WILDCARD {
                self.wildcard[position].push(index);
            } else {
                self.exact[position].entry(token).or_default().push(index);
            }
        }
    }

    /// Returns two lists whose union holds every template that generalizes `tokens` or is generalized by it.
    ///
    /// Both kinds hold, at every position where `tokens` has a literal, that literal or a wildcard, so the templates
    /// with such a token at one position are enough; the position with the fewest of them is chosen. Without a literal
    /// every template of the bucket is a candidate. The caller verifies each candidate.
    fn candidates<'b>(&'b self, tokens: &[&str]) -> (&'b [u32], &'b [u32]) {
        let mut chosen: Option<(&'b [u32], &'b [u32])> = None;
        let mut smallest = self.members.len() + 1;
        for (position, token) in tokens.iter().enumerate() {
            if *token == WILDCARD {
                continue;
            }
            let literal = self.exact[position].get(*token).map_or(&[][..], Vec::as_slice);
            let wildcard = self.wildcard[position].as_slice();
            if literal.len() + wildcard.len() < smallest {
                smallest = literal.len() + wildcard.len();
                chosen = Some((literal, wildcard));
            }
        }
        chosen.unwrap_or((self.members.as_slice(), &[]))
    }
}

/// Pairs templates of equal token count when one generalizes the other; each template is used at most once.
///
/// A wildcard `<*>` matches any token. Templates of `after` are taken in order; each takes the unused template of
/// `before` with the fewest wildcard differences and then the lowest index. Returns `(before index, after index)`
/// pairs in the order of `after`.
pub fn token_subset_pairs(before: &[&str], after: &[&str]) -> Vec<(usize, usize)> {
    let before_tokens: Vec<Vec<&str>> = before.iter().map(|text| tokens(text)).collect();
    let before_wildcards: Vec<usize> = before_tokens.iter().map(|tokens| wildcards(tokens)).collect();
    let mut buckets: HashMap<usize, Bucket<'_>, RandomState> = HashMap::default();
    for (index, tokens) in before_tokens.iter().enumerate() {
        buckets.entry(tokens.len()).or_default().add(index as u32, tokens);
    }
    let mut used = vec![false; before.len()];
    let mut pairs = Vec::new();
    for (j, text) in after.iter().enumerate() {
        let tokens = tokens(text);
        let Some(bucket) = buckets.get(&tokens.len()) else { continue };
        let own = wildcards(&tokens);
        let mut best: Option<(usize, u32)> = None;
        let (first, second) = bucket.candidates(&tokens);
        for &i in first.iter().chain(second) {
            if used[i as usize] {
                continue;
            }
            let candidate = &before_tokens[i as usize];
            if generalizes(candidate, &tokens) || generalizes(&tokens, candidate) {
                let key = (before_wildcards[i as usize].abs_diff(own), i);
                if best.map_or(true, |current| key < current) {
                    best = Some(key);
                }
            }
        }
        if let Some((_, i)) = best {
            used[i as usize] = true;
            pairs.push((i as usize, j));
        }
    }
    pairs
}
