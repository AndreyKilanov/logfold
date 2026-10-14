//! Checks that a masking rule can ask of a candidate before the match is accepted (`docs/ALGORITHM.md` §2).

/// A check run on the text that a rule matched; a candidate that fails it is not a match.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MaskCheck {
    /// A payment card number: 13 to 19 digits (spaces and dashes allowed) with a valid Luhn checksum.
    Luhn,
    /// An IBAN: two letters, two check digits and a national part, 15 to 34 characters (spaces allowed), with a valid
    /// ISO 7064 mod-97 checksum.
    Iban,
}

const CARD_DIGITS: std::ops::RangeInclusive<usize> = 13..=19;
const IBAN_LENGTH: std::ops::RangeInclusive<usize> = 15..=34;

impl MaskCheck {
    /// Returns the check named `name` (`luhn` or `iban`).
    pub fn from_name(name: &str) -> Option<Self> {
        match name {
            "luhn" => Some(MaskCheck::Luhn),
            "iban" => Some(MaskCheck::Iban),
            _ => None,
        }
    }

    /// The name of the check, as written in a rule.
    pub fn name(self) -> &'static str {
        match self {
            MaskCheck::Luhn => "luhn",
            MaskCheck::Iban => "iban",
        }
    }

    /// Tells whether `candidate`, the text a rule matched, passes the check.
    pub fn accepts(self, candidate: &[u8]) -> bool {
        match self {
            MaskCheck::Luhn => luhn(candidate),
            MaskCheck::Iban => iban(candidate),
        }
    }
}

fn luhn(candidate: &[u8]) -> bool {
    let mut digits = 0usize;
    let mut sum = 0u32;
    for &byte in candidate.iter().rev() {
        match byte {
            b'0'..=b'9' => {
                let mut value = u32::from(byte - b'0');
                if digits % 2 == 1 {
                    value *= 2;
                    if value > 9 {
                        value -= 9;
                    }
                }
                sum += value;
                digits += 1;
            }
            b' ' | b'-' => {}
            _ => return false,
        }
    }
    CARD_DIGITS.contains(&digits) && sum.is_multiple_of(10)
}

fn iban(candidate: &[u8]) -> bool {
    let compact: Vec<u8> = candidate.iter().copied().filter(|&byte| byte != b' ').collect();
    if !IBAN_LENGTH.contains(&compact.len()) {
        return false;
    }
    let (head, national) = compact.split_at(4);
    if !head[..2].iter().all(u8::is_ascii_alphabetic) || !head[2..].iter().all(u8::is_ascii_digit) {
        return false;
    }
    let mut remainder = 0u32;
    for &byte in national.iter().chain(head) {
        let value = match byte {
            b'0'..=b'9' => u32::from(byte - b'0'),
            b'A'..=b'Z' => u32::from(byte - b'A') + 10,
            b'a'..=b'z' => u32::from(byte - b'a') + 10,
            _ => return false,
        };
        let shifted = if value >= 10 { remainder * 100 + value } else { remainder * 10 + value };
        remainder = shifted % 97;
    }
    remainder == 1
}
