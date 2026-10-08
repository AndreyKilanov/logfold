use std::io::Read;

/// Size in bytes of the read window a [`LineReader`] starts with; longer lines make it grow.
pub const INITIAL_WINDOW: usize = 4 << 20;

/// Longest line content in bytes. A longer line keeps its first `MAX_LINE_BYTES` bytes and the rest of it is read and
/// dropped, so the window never grows beyond `MAX_LINE_BYTES + INITIAL_WINDOW` whatever the input. The lines of the stream, and
/// their offsets, are the same as without the limit (`docs/ALGORITHM.md` §1.1).
pub const MAX_LINE_BYTES: usize = 16 << 20;

/// One physical line without its terminator.
#[derive(Clone, Copy, Debug)]
pub struct Line<'a> {
    /// Line bytes without `\n` and without one trailing `\r`, at most [`MAX_LINE_BYTES`] of them.
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
    /// The previous line was longer than the limit and its rest is still to be dropped.
    dropping: bool,
}

impl<R: Read> LineReader<R> {
    /// Creates a reader whose first byte has stream offset `start_offset`.
    pub fn new(inner: R, start_offset: u64) -> Self {
        LineReader {
            inner,
            buf: vec![0; INITIAL_WINDOW],
            pos: 0,
            end: 0,
            offset: start_offset,
            eof: false,
            dropping: false,
        }
    }

    /// Stream offset of the next unread byte.
    pub fn offset(&self) -> u64 {
        self.offset
    }

    /// Returns the next line or `None` at the end of the stream.
    ///
    /// Of a line longer than [`MAX_LINE_BYTES`] only the first `MAX_LINE_BYTES` bytes are returned; the rest of the
    /// line, up to and including its line feed, is dropped before the next line is read.
    #[expect(clippy::indexing_slicing, reason = "`pos <= end <= buf.len()` holds after every refill")]
    pub fn next_line(&mut self) -> std::io::Result<Option<Line<'_>>> {
        if self.dropping {
            self.drop_rest_of_line()?;
        }
        loop {
            let available = self.end - self.pos;
            let window = available.min(MAX_LINE_BYTES + 1);
            if let Some(found) = memchr::memchr(b'\n', &self.buf[self.pos..self.pos + window]) {
                return Ok(Some(self.take(found, found + 1, true)));
            }
            if available > MAX_LINE_BYTES {
                self.dropping = true;
                return Ok(Some(self.take(MAX_LINE_BYTES, MAX_LINE_BYTES, false)));
            }
            if self.eof {
                if available > 0 {
                    return Ok(Some(self.take(available, available, true)));
                }
                return Ok(None);
            }
            self.refill()?;
        }
    }

    /// Reads and drops bytes up to and including the next line feed, or to the end of the stream.
    #[expect(clippy::indexing_slicing, reason = "`pos <= end <= buf.len()` holds after every refill")]
    fn drop_rest_of_line(&mut self) -> std::io::Result<()> {
        loop {
            if let Some(found) = memchr::memchr(b'\n', &self.buf[self.pos..self.end]) {
                self.pos += found + 1;
                self.offset += found as u64 + 1;
                self.dropping = false;
                return Ok(());
            }
            self.offset += (self.end - self.pos) as u64;
            self.pos = self.end;
            if self.eof {
                self.dropping = false;
                return Ok(());
            }
            self.refill()?;
        }
    }

    #[expect(clippy::indexing_slicing, reason = "the caller passes lengths inside the window of `buf`")]
    fn take(&mut self, content_len: usize, consumed: usize, strip_cr: bool) -> Line<'_> {
        let begin = self.pos;
        let mut stop = begin + content_len;
        if strip_cr && stop > begin && self.buf[stop - 1] == b'\r' {
            stop -= 1;
        }
        let start = self.offset;
        self.pos += consumed;
        self.offset += consumed as u64;
        Line { bytes: &self.buf[begin..stop], start }
    }

    #[expect(clippy::indexing_slicing, reason = "`pos <= end <= buf.len()` holds after every refill")]
    fn refill(&mut self) -> std::io::Result<()> {
        if self.pos > 0 {
            self.buf.copy_within(self.pos..self.end, 0);
            self.end -= self.pos;
            self.pos = 0;
        }
        if self.end == self.buf.len() {
            let grown = (self.buf.len() * 2).min(MAX_LINE_BYTES + INITIAL_WINDOW);
            self.buf.resize(grown, 0);
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
