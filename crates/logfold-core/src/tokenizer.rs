use crate::error::CoreError;

/// Splits messages into tokens on a fixed set of ASCII delimiter bytes.
#[derive(Clone, Debug)]
pub struct Tokenizer {
    is_delimiter: [bool; 256],
}

impl Tokenizer {
    /// Creates a tokenizer; every delimiter must be an ASCII byte.
    pub fn new(delimiters: &[u8]) -> Result<Self, CoreError> {
        if delimiters.is_empty() {
            return Err(CoreError::InvalidConfig("delimiters must not be empty".into()));
        }
        let mut is_delimiter = [false; 256];
        for &byte in delimiters {
            if !byte.is_ascii() {
                return Err(CoreError::InvalidConfig("delimiters must be ASCII".into()));
            }
            is_delimiter[byte as usize] = true;
        }
        Ok(Tokenizer { is_delimiter })
    }

    /// Fills `spans` with the `(start, end)` byte ranges of the tokens of `buf`.
    pub fn tokenize(&self, buf: &[u8], spans: &mut Vec<(usize, usize)>) {
        spans.clear();
        let mut start = None;
        for (index, &byte) in buf.iter().enumerate() {
            if self.is_delimiter[byte as usize] {
                if let Some(begin) = start.take() {
                    spans.push((begin, index));
                }
            } else if start.is_none() {
                start = Some(index);
            }
        }
        if let Some(begin) = start {
            spans.push((begin, buf.len()));
        }
    }
}

/// Borrowed view of a tokenized message.
#[derive(Clone, Copy, Debug)]
pub struct TokenView<'a> {
    buf: &'a [u8],
    spans: &'a [(usize, usize)],
}

impl<'a> TokenView<'a> {
    /// Creates a view over `buf` described by `spans`.
    pub fn new(buf: &'a [u8], spans: &'a [(usize, usize)]) -> Self {
        TokenView { buf, spans }
    }

    /// Number of tokens.
    pub fn len(&self) -> usize {
        self.spans.len()
    }

    /// True when the message has no tokens.
    pub fn is_empty(&self) -> bool {
        self.spans.is_empty()
    }

    /// Returns token `index`.
    pub fn get(&self, index: usize) -> &'a [u8] {
        let (start, end) = self.spans[index];
        &self.buf[start..end]
    }
}
