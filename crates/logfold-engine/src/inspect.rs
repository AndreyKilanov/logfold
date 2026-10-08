use std::io::Cursor;

use logfold_core::{LEVEL_COUNT, Level};
use logfold_io::{CompiledFormat, FormatConfig, IoError, LineReader, ScanWindow, scan_records};

use crate::error::EngineError;

/// A record of a sample as the format parsed it.
#[derive(Clone, Debug)]
pub struct SampleRecord {
    /// The message, continuation lines included; invalid UTF-8 is replaced.
    pub message: String,
    /// Timestamp in microseconds since the Unix epoch.
    pub timestamp: Option<i64>,
    /// True when the timestamp text carried a time zone.
    pub tz_aware: bool,
    /// Normalized level.
    pub level: Option<Level>,
    /// Physical lines the record spans.
    pub lines: u64,
}

/// What reading a sample shows.
#[derive(Clone, Debug, Default)]
pub struct SampleReport {
    /// The first records.
    pub shown: Vec<SampleRecord>,
    /// Non-blank physical lines of the sample.
    pub lines: u64,
    /// Parsed records.
    pub records: u64,
    /// Lines that did not become part of a record.
    pub unparsed: u64,
    /// Records per level rank.
    pub levels: [u64; LEVEL_COUNT],
    /// Records without a level.
    pub no_level: u64,
    /// Earliest timestamp, in microseconds since the Unix epoch.
    pub first: Option<i64>,
    /// Latest timestamp, in microseconds since the Unix epoch.
    pub last: Option<i64>,
    /// True when any timestamp carried a zone.
    pub tz_aware: bool,
}

/// Reads `sample` (the start of a log) with `config` the way a run reads a file, and reports the counts and the first
/// `keep` records.
pub fn inspect_sample(config: &FormatConfig, sample: &[u8], keep: usize) -> Result<SampleReport, EngineError> {
    let format = CompiledFormat::new(config)?;
    let multiline = format.multiline();
    let mut report = SampleReport::default();
    let reader = LineReader::new(Cursor::new(sample), 0);
    let (counters, _) = scan_records(
        reader,
        &format,
        ScanWindow::whole(),
        |record| {
            match record.level {
                Some(level) => report.levels[level.rank()] += 1,
                None => report.no_level += 1,
            }
            if let Some(timestamp) = record.timestamp {
                report.first = Some(report.first.map_or(timestamp, |first| first.min(timestamp)));
                report.last = Some(report.last.map_or(timestamp, |last| last.max(timestamp)));
            }
            if report.shown.len() < keep {
                let lines =
                    if multiline { 1 + record.message.iter().filter(|&&byte| byte == b'\n').count() } else { 1 };
                report.shown.push(SampleRecord {
                    message: String::from_utf8_lossy(&record.message).into_owned(),
                    timestamp: record.timestamp,
                    tz_aware: record.tz_aware,
                    level: record.level,
                    lines: lines as u64,
                });
            }
        },
        |_| true,
    )
    .map_err(|source| EngineError::Io(IoError::Read { path: "<sample>".into(), source }))?;
    report.lines = counters.lines;
    report.records = counters.records;
    report.unparsed = counters.unparsed;
    report.tz_aware = counters.tz_aware;
    Ok(report)
}
