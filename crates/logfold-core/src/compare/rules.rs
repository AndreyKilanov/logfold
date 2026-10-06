//! The `rules` matcher: pairs templates that a list of rules written by the user declares to be the same event.

use std::collections::HashMap;

use ahash::RandomState;

const WILDCARD: &str = "<*>";

fn tokens(text: &str) -> Vec<&str> {
    if text.is_empty() { Vec::new() } else { text.split(' ').collect() }
}

/// Whether two token lists have the same length and agree at every position, a wildcard agreeing with any token.
fn agree(pattern: &[&str], text: &[&str]) -> bool {
    pattern.len() == text.len() && pattern.iter().zip(text).all(|(p, t)| p == t || *p == WILDCARD || *t == WILDCARD)
}

/// The templates with a given literal at one position, and the templates with a wildcard there.
#[derive(Default)]
struct Position {
    literals: HashMap<String, Vec<u32>, RandomState>,
    wildcards: Vec<u32>,
}

/// The templates of one run that have one token count, indexed by the token at every position.
#[derive(Default)]
struct Bucket {
    members: Vec<u32>,
    positions: Vec<Position>,
}

/// The templates of one run, as token lists and an index by token count and position.
struct Run<'a> {
    templates: Vec<Vec<&'a str>>,
    buckets: HashMap<usize, Bucket, RandomState>,
    used: Vec<bool>,
}

impl<'a> Run<'a> {
    fn new(texts: &[&'a str]) -> Self {
        let templates: Vec<Vec<&str>> = texts.iter().map(|text| tokens(text)).collect();
        let mut buckets: HashMap<usize, Bucket, RandomState> = HashMap::default();
        for (index, template) in templates.iter().enumerate() {
            let bucket = buckets.entry(template.len()).or_default();
            if bucket.positions.is_empty() {
                bucket.positions = (0..template.len()).map(|_| Position::default()).collect();
            }
            bucket.members.push(index as u32);
            for (position, token) in template.iter().enumerate() {
                let slot = &mut bucket.positions[position];
                if *token == WILDCARD {
                    slot.wildcards.push(index as u32);
                } else {
                    slot.literals.entry((*token).to_string()).or_default().push(index as u32);
                }
            }
        }
        Run { templates, buckets, used: vec![false; texts.len()] }
    }

    /// The unused templates that agree with `pattern`, in ascending index order.
    ///
    /// Every such template has, at a position where the pattern holds a literal, that literal or a wildcard, so the
    /// shortest of those lists is searched; without a literal in the pattern the whole bucket is.
    fn matching(&self, pattern: &[&str]) -> Vec<usize> {
        let Some(bucket) = self.buckets.get(&pattern.len()) else {
            return Vec::new();
        };
        let mut best: Option<(&[u32], &[u32])> = None;
        for (position, token) in pattern.iter().enumerate().filter(|(_, token)| **token != WILDCARD) {
            let slot = &bucket.positions[position];
            let literal = slot.literals.get(*token).map_or(&[][..], Vec::as_slice);
            if best.is_none_or(|(l, w)| literal.len() + slot.wildcards.len() < l.len() + w.len()) {
                best = Some((literal, &slot.wildcards));
            }
        }
        let mut found: Vec<usize> = match best {
            Some((literal, wildcards)) => literal.iter().chain(wildcards).map(|&i| i as usize).collect(),
            None => bucket.members.iter().map(|&i| i as usize).collect(),
        };
        found.retain(|&index| !self.used[index] && agree(pattern, &self.templates[index]));
        found.sort_unstable();
        found
    }
}

/// Pairs templates that the rules declare to be the same event.
///
/// A rule is a pair of template texts; its sides are split on the single space character, and a token `<*>` agrees with
/// any token (also on the template's side, where the miner puts it). Rules are tried in the order given. For a rule
/// `(left, right)` the unused templates of the first run that agree with `left` are paired, in ascending order of
/// index, with the unused templates of the second run that agree with `right`; then the same for the first run
/// against `right` and the second against `left`. Each template is used at most once. Returns the pairs sorted by
/// before index.
pub fn rules_pairs(before: &[&str], after: &[&str], rules: &[(&str, &str)]) -> Vec<(usize, usize)> {
    let mut first = Run::new(before);
    let mut second = Run::new(after);
    let mut pairs = Vec::new();
    for &(left, right) in rules {
        let (left, right) = (tokens(left), tokens(right));
        for (against_first, against_second) in [(&left, &right), (&right, &left)] {
            let firsts = first.matching(against_first);
            let seconds = second.matching(against_second);
            for (&i, &j) in firsts.iter().zip(&seconds) {
                first.used[i] = true;
                second.used[j] = true;
                pairs.push((i, j));
            }
        }
    }
    pairs.sort_unstable();
    pairs
}
