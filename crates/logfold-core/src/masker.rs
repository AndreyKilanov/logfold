use regex::bytes::{Regex, RegexBuilder};

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

/// Reusable output buffers for [`RuleMasker::mask`].
#[derive(Default, Debug)]
pub struct MaskScratch {
    a: Vec<u8>,
    b: Vec<u8>,
}

/// Applies an ordered list of masking rules.
#[derive(Clone, Debug)]
pub struct RuleMasker {
    rules: Vec<(Regex, Vec<u8>)>,
}

impl RuleMasker {
    /// Compiles `rules`. A pattern that can match the empty string is rejected.
    pub fn new(rules: &[MaskRule]) -> Result<Self, CoreError> {
        let mut compiled = Vec::with_capacity(rules.len());
        for rule in rules {
            let regex = RegexBuilder::new(&rule.pattern)
                .unicode(!rule.ascii)
                .build()
                .map_err(|e| CoreError::InvalidRule { name: rule.name.clone(), reason: e.to_string() })?;
            if regex.is_match(b"") {
                return Err(CoreError::InvalidRule {
                    name: rule.name.clone(),
                    reason: "pattern matches the empty string".into(),
                });
            }
            compiled.push((regex, rule.token.as_bytes().to_vec()));
        }
        Ok(RuleMasker { rules: compiled })
    }

    /// Returns `input` with all rules applied. The result borrows either `input` or `scratch`.
    pub fn mask<'a>(&self, input: &'a [u8], scratch: &'a mut MaskScratch) -> &'a [u8] {
        let MaskScratch { a, b } = scratch;
        let mut current: Option<bool> = None;
        for (regex, token) in &self.rules {
            let applied = match current {
                None => apply(regex, token, input, a).then_some(true),
                Some(true) => apply(regex, token, a, b).then_some(false),
                Some(false) => apply(regex, token, b, a).then_some(true),
            };
            if applied.is_some() {
                current = applied;
            }
        }
        match current {
            None => input,
            Some(true) => a,
            Some(false) => b,
        }
    }
}

fn apply(regex: &Regex, token: &[u8], src: &[u8], dst: &mut Vec<u8>) -> bool {
    let mut matches = regex.find_iter(src).peekable();
    if matches.peek().is_none() {
        return false;
    }
    dst.clear();
    let mut cursor = 0;
    for found in matches {
        dst.extend_from_slice(&src[cursor..found.start()]);
        dst.extend_from_slice(token);
        cursor = found.end();
    }
    dst.extend_from_slice(&src[cursor..]);
    true
}

#[cfg(test)]
mod tests {
    use super::*;

    fn masked(text: &str) -> String {
        let masker = RuleMasker::new(&default_mask_rules()).unwrap();
        let mut scratch = MaskScratch::default();
        String::from_utf8(masker.mask(text.as_bytes(), &mut scratch).to_vec()).unwrap()
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
    fn rejects_empty_matching_pattern() {
        let rule = MaskRule { name: "bad".into(), pattern: "a*".into(), token: "<A>".into(), ascii: true };
        assert!(RuleMasker::new(&[rule]).is_err());
    }
}
