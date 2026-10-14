use std::borrow::Cow;

use logfold_core::Level;
use regex::bytes::Regex;
use serde_json::Value;

use crate::error::IoError;
use crate::timestamp::{ParsedTimestamp, TimestampFormat, epoch_float_to_micros, epoch_int_to_micros, parse_iso};

/// Declarative description of a log format (see `docs/ALGORITHM.md` §1.2).
#[derive(Clone, Debug)]
pub enum FormatSpec {
    /// The whole record is the message.
    Plain {
        /// Pattern that marks the first line of a record in multiline mode.
        record_start: Option<String>,
    },
    /// One JSON object per line.
    Json {
        /// Candidate keys of the message, first present wins.
        message_keys: Vec<String>,
        /// Candidate keys of the timestamp.
        time_keys: Vec<String>,
        /// Candidate keys of the level.
        level_keys: Vec<String>,
        /// Join an entry whose message does not end with a line break to the entries that follow, up to the one that
        /// does (the pieces of a long line that Docker splits).
        join_unterminated: bool,
    },
    /// A regular expression with named groups.
    Regex {
        /// Pattern searched in the first line of the record.
        pattern: String,
        /// Group holding the message; the whole first line when absent.
        message_group: Option<String>,
        /// Group holding the timestamp text.
        time_group: Option<String>,
        /// Group holding the level text.
        level_group: Option<String>,
    },
}

/// A format specification plus options shared by all kinds.
#[derive(Clone, Debug)]
pub struct FormatConfig {
    /// The format kind and its parameters.
    pub spec: FormatSpec,
    /// `strptime`-style timestamp format; ISO-8601 when absent.
    pub ts_format: Option<String>,
    /// Join continuation lines to the previous record.
    pub multiline: bool,
}

/// One parsed record.
#[derive(Clone, Debug)]
pub struct ParsedRecord<'a> {
    /// Message text.
    pub message: Cow<'a, [u8]>,
    /// Timestamp in microseconds since the Unix epoch.
    pub timestamp: Option<i64>,
    /// True when the timestamp text carried a time zone.
    pub tz_aware: bool,
    /// Normalized level.
    pub level: Option<Level>,
}

enum Kind {
    Plain { record_start: Option<Regex> },
    Json { message_keys: Vec<String>, time_keys: Vec<String>, level_keys: Vec<String>, join: bool },
    Regex { regex: Regex, message: Option<usize>, time: Option<usize>, level: Option<usize> },
}

/// One JSON entry read on its own (see [`CompiledFormat::parse_entry`]).
#[derive(Clone, Debug)]
pub struct Entry {
    /// The message as written, with the line break at its end if it has one.
    pub message: Vec<u8>,
    /// Timestamp in microseconds since the Unix epoch.
    pub timestamp: Option<i64>,
    /// True when the timestamp text carried a time zone.
    pub tz_aware: bool,
    /// Normalized level.
    pub level: Option<Level>,
    /// True when the message ends with a line break, so the entry ends its line.
    pub terminated: bool,
}

/// Joins consecutive entries into one record: from an entry whose message has no line break at its end to the first
/// one that has. The time and the level are those of the first entry.
#[derive(Debug, Default)]
pub struct EntryJoiner {
    message: Vec<u8>,
    head: Option<(Option<i64>, bool, Option<Level>)>,
}

impl EntryJoiner {
    /// True when entries have been added and the line is not finished.
    pub fn is_open(&self) -> bool {
        self.head.is_some()
    }

    /// Adds an entry; returns the record when this entry ends the line. Of a message longer than `limit` bytes the
    /// rest is dropped.
    pub fn push(&mut self, entry: Entry, limit: usize) -> Option<ParsedRecord<'static>> {
        if self.head.is_none() && entry.terminated {
            let mut message = entry.message;
            let kept = without_break_len(&message);
            message.truncate(kept);
            return Some(ParsedRecord {
                message: Cow::Owned(message),
                timestamp: entry.timestamp,
                tz_aware: entry.tz_aware,
                level: entry.level,
            });
        }
        if self.head.is_none() {
            self.head = Some((entry.timestamp, entry.tz_aware, entry.level));
            self.message.clear();
        }
        if self.message.len() < limit {
            self.message.extend_from_slice(&entry.message);
        }
        entry.terminated.then(|| self.take())
    }

    /// Returns the record of the entries that never got their line break (the end of the input, or a line that is not
    /// an entry), or `None` when nothing is open.
    pub fn finish(&mut self) -> Option<ParsedRecord<'static>> {
        self.head.is_some().then(|| self.take())
    }

    fn take(&mut self) -> ParsedRecord<'static> {
        let (timestamp, tz_aware, level) = self.head.take().unwrap_or_default();
        let text = self.message.get(..without_break_len(&self.message)).unwrap_or_default();
        ParsedRecord { message: Cow::Owned(text.to_vec()), timestamp, tz_aware, level }
    }
}

/// A format ready to parse records.
pub struct CompiledFormat {
    kind: Kind,
    ts_format: Option<TimestampFormat>,
    multiline: bool,
}

fn compile_regex(pattern: &str, what: &str) -> Result<Regex, IoError> {
    Regex::new(pattern).map_err(|e| IoError::Format(format!("{what}: {e}")))
}

fn group_index(regex: &Regex, name: &Option<String>) -> Result<Option<usize>, IoError> {
    match name {
        None => Ok(None),
        Some(name) => regex
            .capture_names()
            .position(|candidate| candidate == Some(name.as_str()))
            .map(Some)
            .ok_or_else(|| IoError::Format(format!("pattern has no named group '{name}'"))),
    }
}

impl CompiledFormat {
    /// Compiles `config`, validating patterns, group names and the timestamp format.
    pub fn new(config: &FormatConfig) -> Result<Self, IoError> {
        let ts_format = match &config.ts_format {
            Some(text) => Some(TimestampFormat::new(text).map_err(IoError::Format)?),
            None => None,
        };
        let kind = match &config.spec {
            FormatSpec::Plain { record_start } => {
                let record_start = match record_start {
                    Some(pattern) => Some(compile_regex(pattern, "record_start")?),
                    None => None,
                };
                if config.multiline && record_start.is_none() {
                    return Err(IoError::Format("multiline plain format requires record_start".into()));
                }
                Kind::Plain { record_start }
            }
            FormatSpec::Json { message_keys, time_keys, level_keys, join_unterminated } => {
                if config.multiline {
                    return Err(IoError::Format("json format does not support multiline".into()));
                }
                if message_keys.is_empty() {
                    return Err(IoError::Format("json format needs at least one message key".into()));
                }
                Kind::Json {
                    message_keys: message_keys.clone(),
                    time_keys: time_keys.clone(),
                    level_keys: level_keys.clone(),
                    join: *join_unterminated,
                }
            }
            FormatSpec::Regex { pattern, message_group, time_group, level_group } => {
                let regex = compile_regex(pattern, "pattern")?;
                Kind::Regex {
                    message: group_index(&regex, message_group)?,
                    time: group_index(&regex, time_group)?,
                    level: group_index(&regex, level_group)?,
                    regex,
                }
            }
        };
        Ok(CompiledFormat { kind, ts_format, multiline: config.multiline })
    }

    /// True when continuation lines are joined to the previous record.
    pub fn multiline(&self) -> bool {
        self.multiline
    }

    /// True when an entry whose message has no line break at its end belongs to the record that follows it.
    pub fn joins_entries(&self) -> bool {
        matches!(self.kind, Kind::Json { join: true, .. })
    }

    /// Reads one JSON entry on its own, without dropping the line break at the end of its message.
    ///
    /// Only for a format that [`joins_entries`](Self::joins_entries); `None` means the line is unparsed.
    pub fn parse_entry(&self, line: &[u8]) -> Option<Entry> {
        let Kind::Json { message_keys, time_keys, level_keys, .. } = &self.kind else { return None };
        let value: Value = json_value(line)?;
        let object = value.as_object()?;
        let message = message_keys.iter().find_map(|key| object.get(key))?;
        let (message, terminated) = match message {
            Value::String(text) => (text.clone().into_bytes(), text.ends_with('\n')),
            other => (other.to_string().into_bytes(), true),
        };
        let parsed_time = time_keys.iter().find_map(|key| object.get(key)).and_then(|v| self.json_time(v));
        let level = level_keys
            .iter()
            .find_map(|key| object.get(key))
            .and_then(|v| v.as_str())
            .and_then(|s| Level::parse(s.as_bytes()));
        Some(Entry {
            message,
            timestamp: parsed_time.map(|parsed| parsed.micros),
            tz_aware: parsed_time.is_some_and(|parsed| parsed.tz_aware),
            level,
            terminated,
        })
    }

    /// True when `line` begins a new record (multiline mode).
    pub fn starts_record(&self, line: &[u8]) -> bool {
        match &self.kind {
            Kind::Plain { record_start } => record_start.as_ref().is_some_and(|re| is_match_lossy(re, line)),
            Kind::Json { .. } => line.trim_ascii_start().first() == Some(&b'{'),
            Kind::Regex { regex, .. } => is_match_lossy(regex, line),
        }
    }

    fn parse_time(&self, text: &[u8]) -> Option<ParsedTimestamp> {
        match &self.ts_format {
            Some(format) => format.parse(text).or_else(|| parse_iso(text)),
            None => parse_iso(text),
        }
    }

    /// Parses a record whose first line is `text[..first_len]`; `None` means the record is unparsed.
    pub fn parse<'a>(&self, text: &'a [u8], first_len: usize) -> Option<ParsedRecord<'a>> {
        match &self.kind {
            Kind::Plain { .. } => {
                Some(ParsedRecord { message: Cow::Borrowed(text), timestamp: None, tz_aware: false, level: None })
            }
            Kind::Json { message_keys, time_keys, level_keys, .. } => {
                let value: Value = json_value(text)?;
                let object = value.as_object()?;
                let message = message_keys.iter().find_map(|key| object.get(key))?;
                let message = match message {
                    Value::String(text) => without_line_break(text).as_bytes().to_vec(),
                    other => other.to_string().into_bytes(),
                };
                let parsed_time = time_keys.iter().find_map(|key| object.get(key)).and_then(|v| self.json_time(v));
                let level = level_keys
                    .iter()
                    .find_map(|key| object.get(key))
                    .and_then(|v| v.as_str())
                    .and_then(|s| Level::parse(s.as_bytes()));
                Some(ParsedRecord {
                    message: Cow::Owned(message),
                    timestamp: parsed_time.map(|parsed| parsed.micros),
                    tz_aware: parsed_time.is_some_and(|parsed| parsed.tz_aware),
                    level,
                })
            }
            Kind::Regex { regex, message, time, level } => {
                let (first, continuation) = text.split_at(first_len);
                if let Some(record) = self.read_regex(regex, (*message, *time, *level), first, continuation) {
                    return Some(record);
                }
                if std::str::from_utf8(first).is_ok() {
                    return None;
                }
                // a line in another encoding (Latin-1, Windows-1251) is read with its invalid bytes replaced
                let lossy = String::from_utf8_lossy(first).into_owned().into_bytes();
                let record = self.read_regex(regex, (*message, *time, *level), &lossy, continuation)?;
                Some(ParsedRecord { message: Cow::Owned(record.message.into_owned()), ..record })
            }
        }
    }

    fn read_regex<'a>(
        &self,
        regex: &Regex,
        (message, time, level): (Option<usize>, Option<usize>, Option<usize>),
        first: &'a [u8],
        continuation: &'a [u8],
    ) -> Option<ParsedRecord<'a>> {
        let caps = regex.captures(first)?;
        let head: &[u8] = match message {
            Some(index) => caps.get(index).map_or(&[][..], |m| m.as_bytes()),
            None => first,
        };
        let message = if continuation.is_empty() {
            Cow::Borrowed(head)
        } else {
            let mut joined = Vec::with_capacity(head.len() + continuation.len());
            joined.extend_from_slice(head);
            joined.extend_from_slice(continuation);
            Cow::Owned(joined)
        };
        let parsed_time = time.and_then(|i| caps.get(i)).and_then(|m| self.parse_time(m.as_bytes()));
        let level = level.and_then(|i| caps.get(i)).and_then(|m| Level::parse(m.as_bytes()));
        Some(ParsedRecord {
            message,
            timestamp: parsed_time.map(|parsed| parsed.micros),
            tz_aware: parsed_time.is_some_and(|parsed| parsed.tz_aware),
            level,
        })
    }

    fn json_time(&self, value: &Value) -> Option<ParsedTimestamp> {
        match value {
            Value::String(text) => {
                let digits = text.as_bytes();
                if !digits.is_empty() && digits.len() <= 18 && digits.iter().all(u8::is_ascii_digit) {
                    let int: i64 = text.parse().ok()?;
                    return epoch_int_to_micros(int).map(|micros| ParsedTimestamp { micros, tz_aware: true });
                }
                self.parse_time(digits)
            }
            Value::Number(number) => {
                if let Some(int) = number.as_i64() {
                    epoch_int_to_micros(int).map(|micros| ParsedTimestamp { micros, tz_aware: true })
                } else {
                    number
                        .as_f64()
                        .and_then(epoch_float_to_micros)
                        .map(|micros| ParsedTimestamp { micros, tz_aware: true })
                }
            }
            _ => None,
        }
    }
}

/// Drops one line break (`\n` or `\r\n`) from the end of a message that a JSON log wrote with it.
fn without_line_break(text: &str) -> &str {
    let text = text.strip_suffix('\n').unwrap_or(text);
    text.strip_suffix('\r').unwrap_or(text)
}

/// Length of `bytes` without one line break (`\n` or `\r\n`) at its end.
fn without_break_len(bytes: &[u8]) -> usize {
    let text = bytes.strip_suffix(b"\n").unwrap_or(bytes);
    text.strip_suffix(b"\r").unwrap_or(text).len()
}

/// True when `re` matches `line`, or matches it once the bytes that are not UTF-8 are replaced: a pattern with `.` or
/// `\S` cannot match such a byte, and a log in another encoding would lose every line that has one.
fn is_match_lossy(re: &Regex, line: &[u8]) -> bool {
    re.is_match(line) || (std::str::from_utf8(line).is_err() && re.is_match(String::from_utf8_lossy(line).as_bytes()))
}

/// Reads one JSON value; bytes that are not UTF-8 (a string that was cut in the middle of a character, a log in another
/// encoding) are replaced, so that the line is not lost.
fn json_value(line: &[u8]) -> Option<Value> {
    serde_json::from_slice(line).ok().or_else(|| {
        if std::str::from_utf8(line).is_ok() {
            return None;
        }
        serde_json::from_slice(String::from_utf8_lossy(line).as_bytes()).ok()
    })
}
