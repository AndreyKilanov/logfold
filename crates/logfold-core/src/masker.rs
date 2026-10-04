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

    fn with_regex(rules: &[MaskRule]) -> Result<Self, CoreError> {
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

#[cfg(test)]
mod tests {
    use super::*;

    fn masked_with(rules: &[MaskRule], text: &str) -> String {
        let masker = RuleMasker::new(rules).unwrap();
        let mut scratch = MaskScratch::default();
        String::from_utf8(masker.mask(text.as_bytes(), &mut scratch).to_vec()).unwrap()
    }

    fn masked(text: &str) -> String {
        masked_with(&default_mask_rules(), text)
    }

    #[test]
    fn masks_common_values() {
        assert_eq!(masked("conn from 10.0.0.1:8080 took 12.5 ms"), "conn from <IP> took <NUM> ms");
        assert_eq!(masked("id 123e4567-e89b-12d3-a456-426614174000 ok"), "id <UUID> ok");
        assert_eq!(masked("at 2026-10-04 12:00:01.123Z done"), "at <TS> done");
        assert_eq!(masked("open /var/log/app.log"), "open <PATH>");
        assert_eq!(masked("ptr 0xdeadBEEF"), "ptr <HEX>");
    }

    #[test]
    fn leaves_embedded_digits() {
        assert_eq!(masked("user42 failed"), "user42 failed");
    }

    #[test]
    fn earliest_rule_wins_at_the_same_position() {
        let rules = vec![
            MaskRule { name: "a".into(), pattern: "ab".into(), token: "<A>".into(), ascii: true },
            MaskRule { name: "b".into(), pattern: "abc".into(), token: "<B>".into(), ascii: true },
        ];
        assert_eq!(masked_with(&rules, "xabcx"), "x<A>cx");
    }

    #[test]
    fn leftmost_match_wins_over_rule_order() {
        let rules = vec![
            MaskRule { name: "late".into(), pattern: "cd".into(), token: "<L>".into(), ascii: true },
            MaskRule { name: "early".into(), pattern: "bc".into(), token: "<E>".into(), ascii: true },
        ];
        assert_eq!(masked_with(&rules, "abcd"), "a<E>d");
    }

    #[test]
    fn hand_written_default_masker_matches_the_regex_masker() {
        let fast = RuleMasker::new(&default_mask_rules()).unwrap();
        assert!(fast.default_rules);
        let slow = RuleMasker::with_regex(&default_mask_rules()).unwrap();
        let alphabet: Vec<&[u8]> = vec![
            b"0",
            b"1",
            b"2",
            b"7",
            b"9",
            b"a",
            b"f",
            b"A",
            b"F",
            b"g",
            b"x",
            b"X",
            b"0x",
            b".",
            b".",
            b":",
            b"-",
            b"-",
            b"/",
            b"/",
            b"_",
            b" ",
            b" ",
            b"+",
            b",",
            b"T",
            b"Z",
            b"e",
            b"123",
            b"2026-10-04",
            b"12:00:01",
            b"10.0.0.1",
            b"::",
            b"abcdef12-1234-1234-1234-123456789abc",
            b"x2026-10-04 12:00:01",
            b"blk_-123",
            b"job_2008",
            b"A1b2c3d4-",
            b"1234-",
            b"deadbeef-dead-beef-dead-beefdeadbeef",
            b"zz",
            b"20260-1",
            b"1.2.3.4.5",
            b"v1.2.3",
            b"0x",
        ];
        let mut state: u64 = 0x9E37_79B9_7F4A_7C15;
        let mut next = || {
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            state
        };
        let (mut a, mut b) = (MaskScratch::default(), MaskScratch::default());
        for round in 0..400_000 {
            let pieces = (next() % 14) as usize;
            let mut text = Vec::new();
            for _ in 0..pieces {
                text.extend_from_slice(alphabet[(next() % alphabet.len() as u64) as usize]);
            }
            let expected = slow.mask(&text, &mut a).to_vec();
            let actual = fast.mask(&text, &mut b).to_vec();
            assert_eq!(
                String::from_utf8_lossy(&actual),
                String::from_utf8_lossy(&expected),
                "round {round}, input {:?}",
                String::from_utf8_lossy(&text)
            );
        }
    }

    #[test]
    fn no_rules_leave_the_input_untouched() {
        assert_eq!(masked_with(&[], "keep 12"), "keep 12");
    }

    #[test]
    fn rejects_empty_matching_pattern() {
        let rule = MaskRule { name: "bad".into(), pattern: "a*".into(), token: "<A>".into(), ascii: true };
        assert!(RuleMasker::new(&[rule]).is_err());
    }
}
