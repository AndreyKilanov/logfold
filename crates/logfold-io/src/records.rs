use std::io::Read;

use crate::format::{CompiledFormat, ParsedRecord};
use crate::lines::LineReader;

/// Number of consumed bytes between two progress callbacks.
pub const TICK_BYTES: u64 = 1 << 20;

/// Where a record falls relative to a [`TimeWindow`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Placement {
    /// The record belongs to the window.
    Inside,
    /// The record has a timestamp outside the window.
    Outside,
    /// The record has no timestamp, so it cannot be placed in a window that has a bound.
    Untimed,
}

/// A half-open range of record timestamps in microseconds since the Unix epoch: `since <= timestamp < until`
/// (see `docs/ALGORITHM.md` §8a). A bound that is `None` is open; the default window admits every record.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct TimeWindow {
    /// First admitted timestamp.
    pub since: Option<i64>,
    /// First timestamp that is no longer admitted.
    pub until: Option<i64>,
}

impl TimeWindow {
    /// True when the window has no bound.
    pub fn is_open(&self) -> bool {
        self.since.is_none() && self.until.is_none()
    }

    /// Places a record with `timestamp` relative to the window.
    pub fn place(&self, timestamp: Option<i64>) -> Placement {
        if self.is_open() {
            return Placement::Inside;
        }
        match timestamp {
            None => Placement::Untimed,
            Some(moment) => {
                let after_start = self.since.is_none_or(|since| moment >= since);
                let before_end = self.until.is_none_or(|until| moment < until);
                if after_start && before_end { Placement::Inside } else { Placement::Outside }
            }
        }
    }
}

/// Which part of a stream a scan owns (see `docs/ALGORITHM.md` §8).
#[derive(Clone, Copy, Debug)]
pub struct ScanWindow {
    /// True when the stream starts in the middle of a line; the first (partial) line is discarded.
    pub skip_first_line: bool,
    /// True when leading lines that do not start a record belong to the previous chunk (multiline only).
    pub skip_leading_continuations: bool,
    /// Records whose first line starts at or after this offset belong to the next chunk.
    pub end: u64,
    /// Only records inside this time window are emitted and counted as records.
    pub time: TimeWindow,
}

impl ScanWindow {
    /// A window covering a whole stream.
    pub fn whole() -> Self {
        ScanWindow {
            skip_first_line: false,
            skip_leading_continuations: false,
            end: u64::MAX,
            time: TimeWindow::default(),
        }
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
    /// Records parsed but left out because their timestamp is outside the time window.
    pub out_of_range: u64,
    /// Records parsed but left out because they have no timestamp and the time window has a bound.
    pub untimed: u64,
    /// True when any timestamp carried a zone.
    pub tz_aware: bool,
}

impl Counters {
    /// Adds `other` to `self`.
    pub fn add(&mut self, other: &Counters) {
        self.lines += other.lines;
        self.records += other.records;
        self.unparsed += other.unparsed;
        self.out_of_range += other.out_of_range;
        self.untimed += other.untimed;
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
    time: TimeWindow,
    counters: Counters,
    on_record: F,
}

impl<F: FnMut(&ParsedRecord<'_>)> Scan<'_, F> {
    fn emit(&mut self, text: &[u8], first_len: usize) {
        match self.format.parse(text, first_len) {
            Some(record) => match self.time.place(record.timestamp) {
                Placement::Inside => {
                    self.counters.records += 1;
                    self.counters.tz_aware |= record.tz_aware;
                    (self.on_record)(&record);
                }
                Placement::Outside => self.counters.out_of_range += 1,
                Placement::Untimed => self.counters.untimed += 1,
            },
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
    let mut scan = Scan { format, time: window.time, counters: Counters::default(), on_record };
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
