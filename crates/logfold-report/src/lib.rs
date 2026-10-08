//! Text of the pipeline reports: `github-summary`, `junit`, `chat-message` and `prometheus`.
//!
//! Pure functions from plain rows to a `String`: no I/O and no Python types. The rules (what is cut, escaped or
//! neutralized, byte for byte) are the contract in `docs/ALGORITHM.md`, pinned by the contract tests. Log text is
//! untrusted, so every value that comes from a log goes through [`text`] before it is written.

mod chat;
mod github;
mod junit;
mod prometheus;
pub mod text;

pub use chat::chat_message;
pub use github::github_summary;
pub use junit::junit;
pub use prometheus::prometheus;

/// The levels at which a new template counts as an alert.
pub const ALERT_LEVELS: [&str; 3] = ["WARN", "ERROR", "FATAL"];

/// Whether `level` is WARN or more severe.
pub fn is_alert(level: Option<&str>) -> bool {
    level.is_some_and(|level| ALERT_LEVELS.contains(&level))
}

/// One template of a report: a template of an analysis or an entry of a diff.
#[derive(Debug, Clone, Copy, Default)]
pub struct ReportRow<'a> {
    /// Identifier of the template (16 hex digits).
    pub id: &'a str,
    /// Template text.
    pub text: &'a str,
    /// Most severe level, if the template has one.
    pub level: Option<&'a str>,
    /// Records before (a diff entry); 0 for an analysis template.
    pub before: u64,
    /// Records after (a diff entry) or records of the template (an analysis).
    pub after: u64,
    /// Share ratio of a changed entry.
    pub ratio: Option<f64>,
    /// First moment the template was seen, as ISO 8601 text, or empty.
    pub first_seen: &'a str,
    /// Last moment the template was seen, as ISO 8601 text, or empty.
    pub last_seen: &'a str,
}

/// Counters of one analyzed run.
#[derive(Debug, Clone, Copy, Default)]
pub struct ReportRun<'a> {
    /// Input paths joined with a comma.
    pub name: &'a str,
    /// Parsed records.
    pub records: u64,
    /// Lines that did not become part of a record.
    pub unparsed: u64,
}

/// An analysis result: templates most frequent first.
#[derive(Debug, Clone, Copy)]
pub struct AnalysisInput<'a> {
    /// The run.
    pub run: ReportRun<'a>,
    /// Templates, most frequent first.
    pub templates: &'a [ReportRow<'a>],
    /// Records per level that occurred, least severe first.
    pub levels: &'a [(&'a str, u64)],
    /// Warnings of the run.
    pub warnings: &'a [&'a str],
}

/// A diff result: the entries of each kind, in the order of the result.
#[derive(Debug, Clone, Copy)]
pub struct DiffInput<'a> {
    /// The first run.
    pub before: ReportRun<'a>,
    /// The second run.
    pub after: ReportRun<'a>,
    /// Present after, absent before.
    pub new: &'a [ReportRow<'a>],
    /// Present in both with a significant change.
    pub changed: &'a [ReportRow<'a>],
    /// Present before, absent after.
    pub disappeared: &'a [ReportRow<'a>],
    /// Templates present in both without a significant change.
    pub unchanged: u64,
    /// Warnings of the comparison.
    pub warnings: &'a [&'a str],
}

/// What a report describes.
#[derive(Debug, Clone, Copy)]
pub enum ReportSubject<'a> {
    /// One analyzed run.
    Analysis(AnalysisInput<'a>),
    /// Two runs compared.
    Diff(DiffInput<'a>),
}

/// Indices of `rows` with the WARN+ rows first, each group in its own order.
pub(crate) fn alerts_first(rows: &[ReportRow<'_>]) -> Vec<usize> {
    let alerts = (0..rows.len()).filter(|&i| is_alert(rows[i].level));
    let others = (0..rows.len()).filter(|&i| !is_alert(rows[i].level));
    alerts.chain(others).collect()
}
