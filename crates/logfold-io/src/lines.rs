use std::io::Read;

/// Size in bytes of the read window a [`LineReader`] starts with; longer lines make it grow.
pub const INITIAL_WINDOW: usize = 4 << 20;

/// One physical line without its terminator.
#[derive(Clone, Copy, Debug)]
pub struct Line<'a> {
    /// Line bytes without `\n` and without one trailing `\r`.
    pub bytes: &'a [u8],
    /// Byte offset of the first byte of the line in the stream.
    pub start: u64,
}

/// Splits a byte stream into lines using a large reusable window.
pub struct LineReader<R> {
    inner: R,
    buf: Vec<u8>,
    pos: usize,
    end: usize,
    offset: u64,
    eof: bool,
}

impl<R: Read> LineReader<R> {
    /// Creates a reader whose first byte has stream offset `start_offset`.
    pub fn new(inner: R, start_offset: u64) -> Self {
        LineReader { inner, buf: vec![0; INITIAL_WINDOW], pos: 0, end: 0, offset: start_offset, eof: false }
    }

    /// Stream offset of the next unread byte.
    pub fn offset(&self) -> u64 {
        self.offset
    }

    /// Returns the next line or `None` at the end of the stream.
    pub fn next_line(&mut self) -> std::io::Result<Option<Line<'_>>> {
        loop {
            if let Some(found) = memchr::memchr(b'\n', &self.buf[self.pos..self.end]) {
                return Ok(Some(self.take(found, found + 1)));
            }
            if self.eof {
                if self.pos < self.end {
                    let len = self.end - self.pos;
                    return Ok(Some(self.take(len, len)));
                }
                return Ok(None);
            }
            self.refill()?;
        }
    }

    fn take(&mut self, content_len: usize, consumed: usize) -> Line<'_> {
        let begin = self.pos;
        let mut stop = begin + content_len;
        if stop > begin && self.buf[stop - 1] == b'\r' {
            stop -= 1;
        }
        let start = self.offset;
        self.pos += consumed;
        self.offset += consumed as u64;
        Line { bytes: &self.buf[begin..stop], start }
    }

    fn refill(&mut self) -> std::io::Result<()> {
        if self.pos > 0 {
            self.buf.copy_within(self.pos..self.end, 0);
            self.end -= self.pos;
            self.pos = 0;
        }
        if self.end == self.buf.len() {
            let doubled = self.buf.len() * 2;
            self.buf.resize(doubled, 0);
        }
        loop {
            match self.inner.read(&mut self.buf[self.end..]) {
                Ok(0) => {
                    self.eof = true;
                    return Ok(());
                }
                Ok(n) => {
                    self.end += n;
                    return Ok(());
                }
                Err(e) if e.kind() == std::io::ErrorKind::Interrupted => {}
                Err(e) => return Err(e),
            }
        }
    }
}
