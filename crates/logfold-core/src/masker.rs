use regex::bytes::RegexBuilder;
use regex_automata::meta::Regex;
use regex_automata::util::syntax;

use crate::error::CoreError;

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
}

/// Returns the default rule set from `docs/ALGORITHM.md` §2.
pub fn default_mask_rules() -> Vec<MaskRule> {
    let rule = |name: &str, pattern: &str, token: &str| MaskRule {
        name: name.into(),
        pattern: pattern.into(),
        token: token.into(),
        ascii: true,
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

/// Reusable output buffer for [`RuleMasker::mask`].
#[derive(Default, Debug)]
pub struct MaskScratch {
    buf: Vec<u8>,
}

/// Applies an ordered list of masking rules in a single left-to-right pass.
///
/// At every position the leftmost match wins, and among rules matching at the same position the earliest rule wins
/// (the semantics of the alternation `(rule 1)|(rule 2)|...`).
#[derive(Clone, Debug)]
pub struct RuleMasker {
    regex: Option<Regex>,
    tokens: Vec<Vec<u8>>,
    default_rules: bool,
}

fn scoped(rule: &MaskRule) -> String {
    if rule.ascii {
        format!("(?-u:{})", rule.pattern)
    } else {
        rule.pattern.clone()
    }
}

impl RuleMasker {
    /// Compiles `rules`. A pattern that can match the empty string is rejected.
    ///
    /// The default rule set is applied by a hand-written scanner with identical semantics (see
    /// [`default_mask_rules`]); any other rule set goes through the regex engine.
    pub fn new(rules: &[MaskRule]) -> Result<Self, CoreError> {
        let mut masker = Self::with_regex(rules)?;
        masker.default_rules = rules == default_mask_rules().as_slice();
        Ok(masker)
    }

    /// Builds a masker that always runs the regex engine, even for the default rules.
    ///
    /// It is the oracle the hand-written scanner of the default rules is tested against.
    pub fn with_regex(rules: &[MaskRule]) -> Result<Self, CoreError> {
        for rule in rules {
            let single = RegexBuilder::new(&rule.pattern)
                .unicode(!rule.ascii)
                .build()
                .map_err(|e| CoreError::InvalidRule { name: rule.name.clone(), reason: e.to_string() })?;
            if single.is_match(b"") {
                return Err(CoreError::InvalidRule {
                    name: rule.name.clone(),
                    reason: "pattern matches the empty string".into(),
                });
            }
        }
        let regex = if rules.is_empty() {
            None
        } else {
            let patterns: Vec<String> = rules.iter().map(scoped).collect();
            let built = Regex::builder()
                .syntax(syntax::Config::new().utf8(false))
                .build_many(&patterns)
                .map_err(|e| CoreError::InvalidConfig(format!("cannot combine the mask rules: {e}")))?;
            Some(built)
        };
        Ok(RuleMasker {
            regex,
            tokens: rules.iter().map(|r| r.token.as_bytes().to_vec()).collect(),
            default_rules: false,
        })
    }

    /// Tells whether the hand-written scanner of the default rules is used instead of the regex engine.
    pub fn uses_default_scanner(&self) -> bool {
        self.default_rules
    }

    /// Returns `input` with all rules applied. The result borrows either `input` or `scratch`.
    pub fn mask<'a>(&self, input: &'a [u8], scratch: &'a mut MaskScratch) -> &'a [u8] {
        if self.default_rules {
            return if crate::default_masks::mask_default(input, &mut scratch.buf) { &scratch.buf } else { input };
        }
        let Some(regex) = &self.regex else { return input };
        let mut matches = regex.find_iter(input).peekable();
        if matches.peek().is_none() {
            return input;
        }
        let out = &mut scratch.buf;
        out.clear();
        let mut cursor = 0;
        for found in matches {
            out.extend_from_slice(&input[cursor..found.start()]);
            out.extend_from_slice(&self.tokens[found.pattern().as_usize()]);
            cursor = found.end();
        }
        out.extend_from_slice(&input[cursor..]);
        out
    }
}
