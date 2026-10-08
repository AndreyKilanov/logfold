//! Small pieces shared by the two forms of a state file: counts, byte cursor, variable-length integers and hex.

use logfold_core::MinerSnapshot;

use super::{StateError, damaged};

/// Sizes that a state file declares in its header and that decoding checks against what it finds.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StateCounts {
    /// Nodes of the tree.
    pub nodes: u64,
    /// Templates in the tree.
    pub clusters: u64,
    /// Overflow templates.
    pub overflow: u64,
    /// Bytes of all tokens: the tokens of the templates, of the overflow templates and the keys of the children.
    pub token_bytes: u64,
}

/// Counts what a snapshot holds.
pub(super) fn counts_of(snapshot: &MinerSnapshot) -> StateCounts {
    let keys: usize = snapshot.nodes.iter().flat_map(|n| n.children.iter()).map(|(key, _)| key.len()).sum();
    let templates: usize = snapshot.clusters.iter().flat_map(|c| c.tokens.iter()).map(|t| t.len()).sum();
    let overflow: usize = snapshot.overflow.iter().flat_map(|(_, c)| c.tokens.iter()).map(|t| t.len()).sum();
    StateCounts {
        nodes: snapshot.nodes.len() as u64,
        clusters: snapshot.clusters.len() as u64,
        overflow: snapshot.overflow.len() as u64,
        token_bytes: (keys + templates + overflow) as u64,
    }
}

/// Reads fixed and variable-length numbers and byte strings from a slice, failing instead of panicking at the end.
pub(super) struct Cursor<'a> {
    data: &'a [u8],
    position: usize,
}

impl<'a> Cursor<'a> {
    pub(super) fn new(data: &'a [u8]) -> Self {
        Cursor { data, position: 0 }
    }

    pub(super) fn remaining(&self) -> usize {
        self.data.len() - self.position
    }

    pub(super) fn bytes(&mut self, length: usize) -> Result<&'a [u8], StateError> {
        if length > self.remaining() {
            return Err(damaged("the file ends in the middle of a value"));
        }
        let slice = &self.data[self.position..self.position + length];
        self.position += length;
        Ok(slice)
    }

    pub(super) fn u16_le(&mut self) -> Result<u16, StateError> {
        Ok(u16::from_le_bytes(self.bytes(2)?.try_into().expect("two bytes")))
    }

    pub(super) fn u32_le(&mut self) -> Result<u32, StateError> {
        Ok(u32::from_le_bytes(self.bytes(4)?.try_into().expect("four bytes")))
    }

    pub(super) fn i64_le(&mut self) -> Result<i64, StateError> {
        Ok(i64::from_le_bytes(self.bytes(8)?.try_into().expect("eight bytes")))
    }

    /// An unsigned LEB128 number of at most 64 bits.
    pub(super) fn varint(&mut self) -> Result<u64, StateError> {
        let mut value = 0u64;
        for shift in (0..70).step_by(7) {
            let byte = self.bytes(1)?[0];
            if shift == 63 && byte > 1 {
                return Err(damaged("a number does not fit 64 bits"));
            }
            value |= u64::from(byte & 0x7f) << shift;
            if byte & 0x80 == 0 {
                return Ok(value);
            }
        }
        Err(damaged("a number is too long"))
    }

    /// A count of items that each take at least `min_bytes`; refuses a count the rest of the data cannot hold.
    pub(super) fn count(&mut self, min_bytes: usize, limit: u64, what: &str) -> Result<usize, StateError> {
        let value = self.varint()?;
        if value > limit {
            return Err(super::over(format!("{what}: {value}, at most {limit}")));
        }
        if value.saturating_mul(min_bytes as u64) > self.remaining() as u64 {
            return Err(damaged(format!("{what}: the file is too short for {value} items")));
        }
        Ok(value as usize)
    }

    pub(super) fn finished(&self) -> bool {
        self.remaining() == 0
    }
}

pub(super) fn put_varint(out: &mut Vec<u8>, mut value: u64) {
    loop {
        let byte = (value & 0x7f) as u8;
        value >>= 7;
        if value == 0 {
            out.push(byte);
            return;
        }
        out.push(byte | 0x80);
    }
}

pub(super) fn to_hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut text = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        text.push(DIGITS[(byte >> 4) as usize] as char);
        text.push(DIGITS[(byte & 15) as usize] as char);
    }
    text
}

pub(super) fn from_hex(text: &str) -> Result<Vec<u8>, StateError> {
    let digits = text.as_bytes();
    if !digits.len().is_multiple_of(2) {
        return Err(damaged("a hex string has an odd length"));
    }
    let value = |digit: u8| match digit {
        b'0'..=b'9' => Ok(digit - b'0'),
        b'a'..=b'f' => Ok(digit - b'a' + 10),
        _ => Err(damaged("a hex string has a character that is not a lower-case hex digit")),
    };
    digits.chunks(2).map(|pair| Ok(value(pair[0])? << 4 | value(pair[1])?)).collect()
}
