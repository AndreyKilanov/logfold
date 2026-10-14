use regex::bytes::RegexBuilder;
use regex_automata::Input;
use regex_automata::meta::Regex;
use regex_automata::util::syntax;

use crate::default_masks::{append_masked_default, mask_default, matches_default};
use crate::error::CoreError;
use crate::mask_check::MaskCheck;

/// The largest number of rules in one masker.
pub const MAX_MASK_RULES: usize = 256;
/// The longest pattern of one rule, in bytes.
pub const MAX_PATTERN_BYTES: usize = 4096;

/// A masking rule: every match of `pattern` is replaced with `token`.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct MaskRule {
    /// Rule name, used in error messages.
    pub name: String,
    /// Regular expression (Rust `regex` syntax, byte mode).
    pub pattern: String,
    /// Replacement text.
    pub token: String,
    /// Compile in ASCII mode (`\d`, `\w`, `\b` are ASCII only).
    pub ascii: bool,
    /// A check that a match must pass; a match that fails it is skipped (see `docs/ALGORITHM.md` §2).
    pub check: Option<MaskCheck>,
}

/// Returns the default rule set from `docs/ALGORITHM.md` §2.
pub fn default_mask_rules() -> Vec<MaskRule> {
    let rule = |name: &str, pattern: &str, token: &str| MaskRule {
        name: name.into(),
        pattern: pattern.into(),
        token: token.into(),
        ascii: true,
        check: None,
    };
    vec![
        rule("uuid", r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>"),
        rule("ts", r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?", "<TS>"),
        rule("ip", r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b", "<IP>"),
        rule("hex", r"\b0[xX][0-9a-fA-F]+\b", "<HEX>"),
        rule("path", r"(?:/[\w.\-]+){2,}", "<PATH>"),
        rule("num", r"\b[+-]?\d+(?:\.\d+)?\b", "<NUM>"),
    ]
}

/// One match of a masking rule in a message.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct MaskHit {
    /// Index of the rule in the rule list.
    pub rule: usize,
    /// Start of the match in the message, in bytes.
    pub start: usize,
    /// End of the match in the message, in bytes.
    pub end: usize,
}

/// Reusable output buffer for [`RuleMasker::mask`].
#[derive(Default, Debug)]
pub struct MaskScratch {
    buf: Vec<u8>,
}

/// The first layer: the rules that stand before the default rules, matched together in one pass.
#[derive(Clone, Debug)]
struct Selected {
    regex: Regex,
    checks: Vec<Option<MaskCheck>>,
}

impl Selected {
    /// The leftmost match at or after `from` that passes its check: `(start, end, rule)`.
    ///
    /// A match that fails its check stands for no match at its start, and the search goes on from the next byte.
    fn find(&self, input: &[u8], mut from: usize) -> Option<(usize, usize, usize)> {
        while from <= input.len() {
            let found = self.regex.search(&Input::new(input).span(from..input.len()))?;
            let rule = found.pattern().as_usize();
            if let Some(check) = self.checks[rule]
                && !check.accepts(&input[found.start()..found.end()])
            {
                from = found.start() + 1;
                continue;
            }
            return Some((found.start(), found.end(), rule));
        }
        None
    }
}

/// The second layer: the default rules, applied to the text that the first layer leaves.
#[derive(Clone, Debug)]
struct Fallback {
    regex: Regex,
    scanner: bool,
}

/// Applies an ordered list of masking rules (`docs/ALGORITHM.md` §2).
///
/// Rules that stand before the default rules form the first layer: they run in one left-to-right pass, at every
/// position the leftmost match wins, and among rules matching at the same position the earliest rule wins (the semantics
/// of the alternation `(rule 1)|(rule 2)|...`). The default rules, when they end the list, form the second layer, which
/// runs over the text between the matches of the first. A list without the default rules at its end is one layer.
#[derive(Clone, Debug)]
pub struct RuleMasker {
    selected: Option<Selected>,
    fallback: Option<Fallback>,
    tokens: Vec<Vec<u8>>,
    names: Vec<String>,
}

fn scoped(rule: &MaskRule) -> String {
    if rule.ascii { format!("(?-u:{})", rule.pattern) } else { rule.pattern.clone() }
}

fn invalid(rule: &MaskRule, reason: impl Into<String>) -> CoreError {
    CoreError::InvalidRule { name: rule.name.clone(), reason: reason.into() }
}

fn validate(rule: &MaskRule) -> Result<(), CoreError> {
    if rule.pattern.len() > MAX_PATTERN_BYTES {
        return Err(invalid(rule, format!("the pattern is longer than {MAX_PATTERN_BYTES} bytes")));
    }
    let single =
        RegexBuilder::new(&rule.pattern).unicode(!rule.ascii).build().map_err(|e| invalid(rule, e.to_string()))?;
    if single.is_match(b"") {
        return Err(invalid(rule, "pattern matches the empty string"));
    }
    Ok(())
}

fn combine(rules: &[MaskRule]) -> Result<Regex, CoreError> {
    let patterns: Vec<String> = rules.iter().map(scoped).collect();
    Regex::builder()
        .syntax(syntax::Config::new().utf8(false))
        .build_many(&patterns)
        .map_err(|e| CoreError::InvalidConfig(format!("cannot combine the mask rules: {e}")))
}

impl RuleMasker {
    /// Compiles `rules`. A pattern that can match the empty string is rejected, and so is a list of more than
    /// [`MAX_MASK_RULES`] rules or a pattern longer than [`MAX_PATTERN_BYTES`].
    ///
    /// The default rules at the end of the list are applied by a hand-written scanner with identical semantics (see
    /// [`default_mask_rules`]); the other rules go through the regex engine.
    pub fn new(rules: &[MaskRule]) -> Result<Self, CoreError> {
        Self::build(rules, true)
    }

    /// Builds a masker that always runs the regex engine, even for the default rules.
    ///
    /// It is the oracle the hand-written scanner of the default rules is tested against.
    pub fn with_regex(rules: &[MaskRule]) -> Result<Self, CoreError> {
        Self::build(rules, false)
    }

    fn build(rules: &[MaskRule], scanner: bool) -> Result<Self, CoreError> {
        if rules.len() > MAX_MASK_RULES {
            return Err(CoreError::InvalidConfig(format!("at most {MAX_MASK_RULES} mask rules are allowed")));
        }
        rules.iter().try_for_each(validate)?;
        let defaults = default_mask_rules();
        let split = if rules.ends_with(&defaults) { rules.len() - defaults.len() } else { rules.len() };
        let (head, tail) = rules.split_at(split);
        let fallback = if tail.is_empty() { None } else { Some(Fallback { regex: combine(tail)?, scanner }) };
        if fallback.is_some()
            && let Some(rule) = head.iter().find(|rule| matches_default(rule.token.as_bytes()))
        {
            return Err(invalid(rule, "the token would be changed by the default rules"));
        }
        let selected = if head.is_empty() {
            None
        } else {
            Some(Selected { regex: combine(head)?, checks: head.iter().map(|rule| rule.check).collect() })
        };
        Ok(RuleMasker {
            selected,
            fallback,
            tokens: rules.iter().map(|r| r.token.as_bytes().to_vec()).collect(),
            names: rules.iter().map(|r| r.name.clone()).collect(),
        })
    }

    /// Tells whether the hand-written scanner of the default rules is used instead of the regex engine.
    pub fn uses_default_scanner(&self) -> bool {
        self.fallback.as_ref().is_some_and(|fallback| fallback.scanner)
    }

    /// The number of rules of the first layer; the default rules, if any, follow them in the rule numbering.
    fn offset(&self) -> usize {
        self.tokens.len() - self.fallback.as_ref().map_or(0, |fallback| fallback.regex.pattern_len())
    }

    /// Returns the matches that [`RuleMasker::mask`] replaces in `input`, in order, found by the regex engine.
    ///
    /// The default rules give the same matches here as with their hand-written scanner (that is what the scanner is tested
    /// against), so the spans can be paired with the output of `mask`. The spans are positions in `input`.
    pub fn hits(&self, input: &[u8]) -> Vec<MaskHit> {
        let mut hits = Vec::new();
        let mut cursor = 0;
        if let Some(selected) = &self.selected {
            let mut from = 0;
            while let Some((start, end, rule)) = selected.find(input, from) {
                self.fallback_hits(input, cursor, start, &mut hits);
                hits.push(MaskHit { rule, start, end });
                cursor = end;
                from = end;
            }
        }
        self.fallback_hits(input, cursor, input.len(), &mut hits);
        hits
    }

    fn fallback_hits(&self, input: &[u8], from: usize, to: usize, hits: &mut Vec<MaskHit>) {
        let Some(fallback) = &self.fallback else { return };
        let offset = self.offset();
        for found in fallback.regex.find_iter(&input[from..to]) {
            hits.push(MaskHit {
                rule: offset + found.pattern().as_usize(),
                start: from + found.start(),
                end: from + found.end(),
            });
        }
    }

    /// The replacement text of rule `rule`.
    pub fn token(&self, rule: usize) -> &[u8] {
        &self.tokens[rule]
    }

    /// The name of rule `rule`.
    pub fn name(&self, rule: usize) -> &str {
        &self.names[rule]
    }

    /// Returns `input` with all rules applied. The result borrows either `input` or `scratch`.
    pub fn mask<'a>(&self, input: &'a [u8], scratch: &'a mut MaskScratch) -> &'a [u8] {
        let first = self.selected.as_ref().and_then(|selected| selected.find(input, 0));
        let (Some(selected), Some(mut found)) = (&self.selected, first) else {
            return self.mask_fallback(input, scratch);
        };
        let out = &mut scratch.buf;
        out.clear();
        let mut cursor = 0;
        loop {
            let (start, end, rule) = found;
            self.append_fallback(&input[cursor..start], out);
            out.extend_from_slice(&self.tokens[rule]);
            cursor = end;
            match selected.find(input, end) {
                Some(next) => found = next,
                None => break,
            }
        }
        self.append_fallback(&input[cursor..], out);
        out
    }

    /// Applies only the second layer (the default rules), borrowing `input` when nothing matches.
    fn mask_fallback<'a>(&self, input: &'a [u8], scratch: &'a mut MaskScratch) -> &'a [u8] {
        let Some(fallback) = &self.fallback else { return input };
        if fallback.scanner {
            return if mask_default(input, &mut scratch.buf) { &scratch.buf } else { input };
        }
        let mut matches = fallback.regex.find_iter(input).peekable();
        if matches.peek().is_none() {
            return input;
        }
        let out = &mut scratch.buf;
        out.clear();
        let offset = self.offset();
        let mut cursor = 0;
        for found in matches {
            out.extend_from_slice(&input[cursor..found.start()]);
            out.extend_from_slice(&self.tokens[offset + found.pattern().as_usize()]);
            cursor = found.end();
        }
        out.extend_from_slice(&input[cursor..]);
        out
    }

    /// Appends `text`, a piece between two matches of the first layer, with the second layer applied.
    fn append_fallback(&self, text: &[u8], out: &mut Vec<u8>) {
        let Some(fallback) = &self.fallback else {
            out.extend_from_slice(text);
            return;
        };
        if fallback.scanner {
            append_masked_default(text, out);
            return;
        }
        let offset = self.offset();
        let mut cursor = 0;
        for found in fallback.regex.find_iter(text) {
            out.extend_from_slice(&text[cursor..found.start()]);
            out.extend_from_slice(&self.tokens[offset + found.pattern().as_usize()]);
            cursor = found.end();
        }
        out.extend_from_slice(&text[cursor..]);
    }
}
