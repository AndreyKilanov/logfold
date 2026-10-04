use std::io::Read;

use crate::format::{CompiledFormat, ParsedRecord};
use crate::lines::LineReader;

/// Number of consumed bytes between two progress callbacks.
pub const TICK_BYTES: u64 = 16 << 20;

/// Which part of a stream a scan owns (see `docs/ALGORITHM.md` §8).
#[derive(Clone, Copy, Debug)]
pub struct ScanWindow {
    /// True when the stream starts in the middle of a line; the first (partial) line is discarded.
    pub skip_first_line: bool,
    /// True when leading lines that do not start a record belong to the previous chunk (multiline only).
    pub skip_leading_continuations: bool,
    /// Records whose first line starts at or after this offset belong to the next chunk.
    pub end: u64,
}

impl ScanWindow {
    /// A window covering a whole stream.
    pub fn whole() -> Self {
        ScanWindow { skip_first_line: false, skip_leading_continuations: false, end: u64::MAX }
    }
}

/// Counters of one scan.
#[derive(Clone, Copy, Debug, Default)]
pub struct Counters {
    /// Non-skipped physical lines.
    pub lines: u64,
    /// Parsed records.
    pub records: u64,
    /// Lines that did not become part of a record.
    pub unparsed: u64,
    /// True when any timestamp carried a zone.
    pub tz_aware: bool,
}

impl Counters {
    /// Adds `other` to `self`.
    pub fn add(&mut self, other: &Counters) {
        self.lines += other.lines;
        self.records += other.records;
        self.unparsed += other.unparsed;
        self.tz_aware |= other.tz_aware;
    }
}

/// How a scan ended.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum ScanOutcome {
    /// The window was fully consumed.
    Finished,
    /// The progress callback asked to stop.
    Stopped,
}

fn is_blank(line: &[u8]) -> bool {
    line.iter().all(u8::is_ascii_whitespace)
}

struct Scan<'f, F> {
    format: &'f CompiledFormat,
    counters: Counters,
    on_record: F,
}

impl<F: FnMut(&ParsedRecord<'_>)> Scan<'_, F> {
    fn emit(&mut self, text: &[u8], first_len: usize) {
        match self.format.parse(text, first_len) {
            Some(record) => {
                self.counters.records += 1;
                self.counters.tz_aware |= record.tz_aware;
                (self.on_record)(&record);
            }
            None => self.counters.unparsed += 1,
        }
    }
}

/// Reads records from `reader` inside `window`, calling `on_record` for each one.
///
/// `tick` receives the number of bytes consumed since its previous call (every [`TICK_BYTES`]) and returns `false`
/// to stop the scan.
pub fn scan_records<R: Read, F: FnMut(&ParsedRecord<'_>)>(
    mut reader: LineReader<R>,
    format: &CompiledFormat,
    window: ScanWindow,
    on_record: F,
    mut tick: impl FnMut(u64) -> bool,
) -> std::io::Result<(Counters, ScanOutcome)> {
    let mut scan = Scan { format, counters: Counters::default(), on_record };
    let mut skip_first = window.skip_first_line;
    let mut leading = window.skip_leading_continuations;
    let mut record = Vec::new();
    let mut first_len = 0usize;
    let mut open = false;
    let mut last_tick = reader.offset();

    while let Some(line) = reader.next_line()? {
        if skip_first {
            skip_first = false;
            continue;
        }
        let start = line.start;
        let bytes = line.bytes;
        let consumed_to = start + bytes.len() as u64 + 1;
        if format.multiline() {
            if !is_blank(bytes) && format.starts_record(bytes) {
                if open {
                    scan.emit(&record, first_len);
                    open = false;
                }
                if start >= window.end {
                    break;
                }
                leading = false;
                scan.counters.lines += 1;
                record.clear();
                record.extend_from_slice(bytes);
                first_len = bytes.len();
                open = true;
            } else if !leading {
                scan.counters.lines += 1;
                if !is_blank(bytes) {
                    if open {
                        record.push(b'\n');
                        record.extend_from_slice(bytes);
                    } else {
                        scan.counters.unparsed += 1;
                    }
                }
            }
        } else {
            if start >= window.end {
                break;
            }
            scan.counters.lines += 1;
            if !is_blank(bytes) {
                scan.emit(bytes, bytes.len());
            }
        }
        if consumed_to - last_tick >= TICK_BYTES {
            let delta = consumed_to - last_tick;
            last_tick = consumed_to;
            if !tick(delta) {
                return Ok((scan.counters, ScanOutcome::Stopped));
            }
        }
    }
    if open {
        scan.emit(&record, first_len);
    }
    let delta = reader.offset().saturating_sub(last_tick);
    if delta > 0 {
        tick(delta);
    }
    Ok((scan.counters, ScanOutcome::Finished))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::format::{FormatConfig, FormatSpec};

    fn plain(multiline: bool) -> CompiledFormat {
        CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Plain { record_start: multiline.then(|| r"^\d{4}-".to_string()) },
            ts_format: None,
            multiline,
        })
        .unwrap()
    }

    fn run(data: &[u8], format: &CompiledFormat, window: ScanWindow, offset: u64) -> (Vec<String>, Counters) {
        let mut messages = Vec::new();
        let (counters, _) = scan_records(
            LineReader::new(data, offset),
            format,
            window,
            |rec| messages.push(String::from_utf8_lossy(&rec.message).into_owned()),
            |_| true,
        )
        .unwrap();
        (messages, counters)
    }

    #[test]
    fn single_line_records_skip_blank_lines() {
        let (messages, counters) = run(b"a\n\nb\r\nc", &plain(false), ScanWindow::whole(), 0);
        assert_eq!(messages, vec!["a", "b", "c"]);
        assert_eq!((counters.lines, counters.records, counters.unparsed), (4, 3, 0));
    }

    #[test]
    fn multiline_joins_continuations_and_counts_leading_garbage() {
        let data = b"junk\n2026-01 first\n  cont\n2026-02 second\n";
        let (messages, counters) = run(data, &plain(true), ScanWindow::whole(), 0);
        assert_eq!(messages, vec!["2026-01 first\n  cont", "2026-02 second"]);
        assert_eq!((counters.lines, counters.records, counters.unparsed), (4, 2, 1));
    }

    #[test]
    fn chunks_partition_records_exactly() {
        let data = b"junk\n\n2026-01 a\n  x\n\n2026-02 b\n2026-03 c\n  y\n\n  z\n2026-04 d\n\n";
        let format = plain(true);
        let mut all = Vec::new();
        let mut total = Counters::default();
        for split in 1..data.len() {
            all.clear();
            total = Counters::default();
            let bounds = [(0u64, split as u64), (split as u64, u64::MAX)];
            for (start, end) in bounds {
                let begin = start.saturating_sub(1);
                let window = ScanWindow { skip_first_line: start > 0, skip_leading_continuations: start > 0, end };
                let (messages, counters) = run(&data[begin as usize..], &format, window, begin);
                all.extend(messages);
                total.add(&counters);
            }
            assert_eq!(all, vec!["2026-01 a\n  x", "2026-02 b", "2026-03 c\n  y\n  z", "2026-04 d"], "split {split}");
            assert_eq!((total.lines, total.records, total.unparsed), (12, 4, 1), "split {split}");
        }
        assert_eq!(all.len(), 4);
        assert_eq!(total.records, 4);
    }
}
