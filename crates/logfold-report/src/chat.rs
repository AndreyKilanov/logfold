//! `chat-message`: a short plain-text message for Slack, Mattermost and Telegram.

use std::fmt::Write as _;

use super::text::{alert_noun, code_span, defuse_mentions, group, push_code_span, push_group, run_names};
use super::{ReportRow, ReportSubject, alerts_first, is_alert};

const NAME_WIDTH: usize = 60;
const TEXT_WIDTH: usize = 200;
/// Room kept for the closing `... and N more` line.
const MORE_RESERVE: usize = 30;

fn push_item(out: &mut String, row: &ReportRow<'_>) {
    out.push_str("- ");
    if let Some(level) = row.level {
        out.push_str(level);
        out.push(' ');
    }
    push_group(out, row.after);
    out.push_str(" x ");
    push_code_span(out, &defuse_mentions(row.text), TEXT_WIDTH, false);
}

/// Render `subject` as a message of at most about `max_chars` characters listing `top` templates.
///
/// Templates are dropped from the end of the list, never cut, until the message fits; the headline is always kept.
pub fn chat_message(subject: &ReportSubject<'_>, top: usize, max_chars: usize) -> String {
    let (head, rows, order): (Vec<String>, &[ReportRow<'_>], Vec<usize>) = match subject {
        ReportSubject::Analysis(analysis) => {
            let run = &analysis.run;
            let head = vec![
                format!("logfold: {}", code_span(&defuse_mentions(run.name), NAME_WIDTH, true)),
                format!(
                    "{} records, {} templates, {} unparsed lines.",
                    group(run.records),
                    group(analysis.templates.len() as u64),
                    group(run.unparsed)
                ),
                "Most frequent templates:".to_owned(),
            ];
            (head, analysis.templates, (0..analysis.templates.len()).collect())
        }
        ReportSubject::Diff(diff) => {
            let alerts = diff.new.iter().filter(|row| is_alert(row.level)).count() as u64;
            let mut head = vec![
                format!("logfold: {}", run_names(diff.before.name, diff.after.name, NAME_WIDTH)),
                format!(
                    "{} of {} new, {} disappeared, {} changed.",
                    alert_noun(alerts),
                    group(diff.new.len() as u64),
                    group(diff.disappeared.len() as u64),
                    group(diff.changed.len() as u64)
                ),
            ];
            if !diff.new.is_empty() {
                head.push("New templates:".to_owned());
            }
            (head, diff.new, alerts_first(diff.new))
        }
    };
    let mut out = head.join("\n");
    let mut used = out.chars().count();
    let mut shown = 0;
    for &index in order.iter().take(top) {
        let before = out.len();
        out.push('\n');
        push_item(&mut out, &rows[index]);
        let length = out[before + 1..].chars().count();
        if used + length + 1 + MORE_RESERVE > max_chars {
            out.truncate(before);
            break;
        }
        used += length + 1;
        shown += 1;
    }
    if shown < order.len() {
        let _ = write!(out, "\n... and {} more", group((order.len() - shown) as u64));
    }
    out.push('\n');
    out
}
