//! The values that a message gives to the variable positions of a template.
//!
//! A template keeps constant tokens and has two kinds of variable positions: `<*>`, which the miner generalized, and the
//! replacement tokens of the masking rules (`<NUM>`, `<IP>`, ...), which stand for the values that the rules masked. This
//! module masks and tokenizes a message exactly as the miner does, aligns the tokens with the template and gives back the
//! text of every variable part as it was written in the message.

use crate::masker::{MaskHit, RuleMasker};
use crate::miner::WILDCARD;
use crate::tokenizer::Tokenizer;

/// The name of a parameter at a position that the miner generalized.
pub const WILDCARD_NAME: &str = "*";

/// How strictly a message has to fit a template.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Fit {
    /// Every constant token of the template equals the token of the message.
    Exact,
    /// Only the number of tokens has to be the same: constant tokens that differ are ignored, as when a record is assigned
    /// to a template by similarity.
    ByPosition,
}

/// One value of a message at a variable position of a template.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Parameter {
    /// Index of the token in the template (and in the masked message).
    pub position: usize,
    /// The name of the masking rule that matched the value, or [`WILDCARD_NAME`] for a generalized position.
    pub name: String,
    /// The value as it was written in the message.
    pub value: Vec<u8>,
}

struct Replacement {
    masked_start: usize,
    masked_end: usize,
    hit: MaskHit,
}

/// Masks `message`, remembering where each replacement stands in the masked text.
fn mask_with_replacements(masker: &RuleMasker, message: &[u8]) -> (Vec<u8>, Vec<Replacement>) {
    let mut masked = Vec::with_capacity(message.len());
    let mut replacements = Vec::new();
    let mut cursor = 0;
    for hit in masker.hits(message) {
        masked.extend_from_slice(&message[cursor..hit.start]);
        let masked_start = masked.len();
        masked.extend_from_slice(masker.token(hit.rule));
        replacements.push(Replacement { masked_start, masked_end: masked.len(), hit });
        cursor = hit.end;
    }
    masked.extend_from_slice(&message[cursor..]);
    (masked, replacements)
}

/// Maps an offset of the masked text back into the message. An offset inside a replacement goes to the start (when `end`
/// is false) or to the end (when `end` is true) of the text that the replacement stands for.
fn original(offset: usize, replacements: &[Replacement], end: bool) -> usize {
    let mut shift: isize = 0;
    for replacement in replacements {
        if offset < replacement.masked_start {
            break;
        }
        if offset < replacement.masked_end || (end && offset == replacement.masked_end) {
            return if end { replacement.hit.end } else { replacement.hit.start };
        }
        shift = replacement.hit.end as isize - replacement.masked_end as isize;
    }
    offset.checked_add_signed(shift).unwrap_or(offset)
}

/// Gives the values that `message` has at the variable positions of `template`, in the order of the positions.
///
/// `template` holds the tokens of a template (the text of a template split at its single spaces). The message is masked with
/// `masker` and tokenized with `tokenizer`, which must be the ones that the template was mined with. A `<*>` token gives one
/// parameter with the whole token as written (the masked values inside it are not given separately); a constant token that
/// holds replacements of the masking rules gives one parameter for each of them, named by the rule.
///
/// Returns `None` when the message has another number of tokens than the template, or, with [`Fit::Exact`], when a
/// constant token differs.
pub fn extract_parameters(
    masker: &RuleMasker,
    tokenizer: &Tokenizer,
    template: &[&[u8]],
    message: &[u8],
    fit: Fit,
) -> Option<Vec<Parameter>> {
    let (masked, replacements) = mask_with_replacements(masker, message);
    let mut spans = Vec::new();
    tokenizer.tokenize(&masked, &mut spans);
    if spans.len() != template.len() {
        return None;
    }
    let mut parameters = Vec::new();
    let mut next = 0;
    for (position, (&expected, &(start, end))) in template.iter().zip(&spans).enumerate() {
        let inside = |replacement: &Replacement| replacement.masked_start < end;
        if expected == WILDCARD {
            let value = message[original(start, &replacements, false)..original(end, &replacements, true)].to_vec();
            parameters.push(Parameter { position, name: WILDCARD_NAME.to_string(), value });
            while replacements.get(next).is_some_and(inside) {
                next += 1;
            }
            continue;
        }
        if fit == Fit::Exact && expected != &masked[start..end] {
            return None;
        }
        while let Some(replacement) = replacements.get(next).filter(|r| inside(r)) {
            if replacement.masked_start >= start {
                let hit = replacement.hit;
                parameters.push(Parameter {
                    position,
                    name: masker.name(hit.rule).to_string(),
                    value: message[hit.start..hit.end].to_vec(),
                });
            }
            next += 1;
        }
    }
    Some(parameters)
}
