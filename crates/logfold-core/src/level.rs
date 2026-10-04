/// Number of known severity levels.
pub const LEVEL_COUNT: usize = 6;

/// Normalized log severity. The discriminant is the severity rank.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Level {
    /// `TRACE`
    Trace = 0,
    /// `DEBUG`
    Debug = 1,
    /// `INFO` (also `NOTICE`, syslog priorities 5 and 6)
    Info = 2,
    /// `WARN` (also `WARNING`)
    Warn = 3,
    /// `ERROR` (also `ERR`)
    Error = 4,
    /// `FATAL` (also `CRITICAL`, `CRIT`, `EMERG`, `ALERT`, `PANIC`)
    Fatal = 5,
}

impl Level {
    /// Canonical upper-case names, indexed by rank.
    pub const NAMES: [&'static str; LEVEL_COUNT] = ["TRACE", "DEBUG", "INFO", "WARN", "ERROR", "FATAL"];

    /// Parses a level name case-insensitively; unknown names yield `None`.
    pub fn parse(text: &[u8]) -> Option<Level> {
        let text = text.trim_ascii();
        if text.is_empty() || text.len() > 8 {
            return None;
        }
        let mut upper = [0u8; 8];
        for (dst, src) in upper.iter_mut().zip(text) {
            *dst = src.to_ascii_uppercase();
        }
        match &upper[..text.len()] {
            b"TRACE" => Some(Level::Trace),
            b"DEBUG" => Some(Level::Debug),
            b"INFO" | b"NOTICE" => Some(Level::Info),
            b"WARN" | b"WARNING" => Some(Level::Warn),
            b"ERROR" | b"ERR" => Some(Level::Error),
            b"FATAL" | b"CRITICAL" | b"CRIT" | b"EMERG" | b"ALERT" | b"PANIC" | b"0" | b"1" | b"2" => {
                Some(Level::Fatal)
            }
            b"3" => Some(Level::Error),
            b"4" => Some(Level::Warn),
            b"5" | b"6" => Some(Level::Info),
            b"7" => Some(Level::Debug),
            _ => None,
        }
    }

    /// Returns the severity rank, `0..LEVEL_COUNT`.
    pub fn rank(self) -> usize {
        self as usize
    }
}
