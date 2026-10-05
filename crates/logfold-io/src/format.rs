use std::borrow::Cow;

use logfold_core::Level;
use regex::bytes::Regex;
use serde_json::Value;

use crate::error::IoError;
use crate::timestamp::{epoch_float_to_micros, epoch_int_to_micros, parse_iso, Parsed, TsFormat};

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
    Json { message_keys: Vec<String>, time_keys: Vec<String>, level_keys: Vec<String> },
    Regex { regex: Regex, message: Option<usize>, time: Option<usize>, level: Option<usize> },
}

/// A format ready to parse records.
pub struct CompiledFormat {
    kind: Kind,
    ts_format: Option<TsFormat>,
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
            Some(text) => Some(TsFormat::new(text).map_err(IoError::Format)?),
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
            FormatSpec::Json { message_keys, time_keys, level_keys } => {
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

    /// True when `line` begins a new record (multiline mode).
    pub fn starts_record(&self, line: &[u8]) -> bool {
        match &self.kind {
            Kind::Plain { record_start } => record_start.as_ref().is_some_and(|re| re.is_match(line)),
            Kind::Json { .. } => line.trim_ascii_start().first() == Some(&b'{'),
            Kind::Regex { regex, .. } => regex.is_match(line),
        }
    }

    fn parse_time(&self, text: &[u8]) -> Option<Parsed> {
        match &self.ts_format {
            Some(format) => format.parse(text),
            None => parse_iso(text),
        }
    }

    /// Parses a record whose first line is `text[..first_len]`; `None` means the record is unparsed.
    pub fn parse<'a>(&self, text: &'a [u8], first_len: usize) -> Option<ParsedRecord<'a>> {
        match &self.kind {
            Kind::Plain { .. } => {
                Some(ParsedRecord { message: Cow::Borrowed(text), timestamp: None, tz_aware: false, level: None })
            }
            Kind::Json { message_keys, time_keys, level_keys } => {
                let value: Value = serde_json::from_slice(text).ok()?;
                let object = value.as_object()?;
                let message = message_keys.iter().find_map(|key| object.get(key))?;
                let message = match message {
                    Value::String(text) => text.clone().into_bytes(),
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
                    timestamp: parsed_time.map(|(micros, _)| micros),
                    tz_aware: parsed_time.is_some_and(|(_, aware)| aware),
                    level,
                })
            }
            Kind::Regex { regex, message, time, level } => {
                let first = &text[..first_len];
                let caps = regex.captures(first)?;
                let continuation = &text[first_len..];
                let head: &[u8] = match message {
                    Some(index) => caps.get(*index).map_or(&[][..], |m| m.as_bytes()),
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
                    timestamp: parsed_time.map(|(micros, _)| micros),
                    tz_aware: parsed_time.is_some_and(|(_, aware)| aware),
                    level,
                })
            }
        }
    }

    fn json_time(&self, value: &Value) -> Option<Parsed> {
        match value {
            Value::String(text) => {
                let digits = text.as_bytes();
                if !digits.is_empty() && digits.len() <= 18 && digits.iter().all(u8::is_ascii_digit) {
                    let int: i64 = text.parse().ok()?;
                    return epoch_int_to_micros(int).map(|micros| (micros, true));
                }
                self.parse_time(digits)
            }
            Value::Number(number) => {
                if let Some(int) = number.as_i64() {
                    epoch_int_to_micros(int).map(|micros| (micros, true))
                } else {
                    number.as_f64().and_then(epoch_float_to_micros).map(|micros| (micros, true))
                }
            }
            _ => None,
        }
    }
}
