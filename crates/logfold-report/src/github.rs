//! `github-summary`: Markdown for `$GITHUB_STEP_SUMMARY`.

use std::fmt::Write as _;

use super::text::{alert_noun, push_code_span, push_group, push_share, run_names};
use super::{AnalysisInput, DiffInput, ReportRow, ReportSubject, alerts_first, is_alert};

const NAME_WIDTH: usize = 80;
const TEXT_WIDTH: usize = 300;

/// Render `subject` as Markdown that stays under `max_bytes`.
///
/// `top` is the number of templates per list (at most the length of the longest list). When the document is larger than the budget the lists are cut to half,
/// then a quarter, and so on, down to none: the headings and the counts are always kept.
pub fn github_summary(subject: &ReportSubject<'_>, top: usize, max_bytes: usize) -> String {
    let longest = match subject {
        ReportSubject::Analysis(analysis) => analysis.templates.len(),
        ReportSubject::Diff(diff) => diff.new.len().max(diff.changed.len()).max(diff.disappeared.len()),
    };
    let top = top.min(longest);
    let mut rows = top;
    loop {
        let text = document(subject, rows, rows < top);
        if text.len() <= max_bytes || rows == 0 {
            return text;
        }
        rows /= 2;
    }
}

fn document(subject: &ReportSubject<'_>, rows: usize, cut: bool) -> String {
    let mut out = String::new();
    match subject {
        ReportSubject::Analysis(analysis) => analysis_lines(&mut out, analysis, rows),
        ReportSubject::Diff(diff) => diff_lines(&mut out, diff, rows),
    }
    if cut {
        let _ = writeln!(out, "\n_Lists are shortened to {rows} templates to fit the size limit of a job summary._");
    }
    out
}

fn line(out: &mut String, text: &str) {
    out.push_str(text);
    out.push('\n');
}

fn push_level(out: &mut String, level: Option<&str>) {
    if let Some(level) = level {
        let _ = write!(out, "**{level}** ");
    }
}

fn entry_line(out: &mut String, row: &ReportRow<'_>, kind: &str) {
    out.push_str("- ");
    push_level(out, row.level);
    match (kind, row.ratio) {
        ("changed", Some(ratio)) => {
            let _ = write!(out, "x{ratio:.2} (");
            push_group(out, row.before);
            out.push_str(" -> ");
            push_group(out, row.after);
            out.push(')');
        }
        ("disappeared", _) => {
            push_group(out, row.before);
            out.push_str(" -> 0");
        }
        _ => push_group(out, row.after),
    }
    out.push(' ');
    push_code_span(out, row.text, TEXT_WIDTH, false);
    out.push('\n');
}

fn template_line(out: &mut String, row: &ReportRow<'_>, records: u64) {
    out.push_str("- ");
    push_level(out, row.level);
    push_group(out, row.after);
    out.push_str(" (");
    push_share(out, row.after, records);
    out.push_str(") ");
    push_code_span(out, row.text, TEXT_WIDTH, false);
    out.push('\n');
}

fn warning_lines(out: &mut String, warnings: &[&str]) {
    if warnings.is_empty() {
        return;
    }
    line(out, "");
    for text in warnings {
        out.push_str("> warning: ");
        push_code_span(out, text, TEXT_WIDTH, false);
        out.push('\n');
    }
}

fn analysis_lines(out: &mut String, analysis: &AnalysisInput<'_>, rows: usize) {
    let run = &analysis.run;
    out.push_str("## logfold: ");
    push_code_span(out, run.name, NAME_WIDTH, true);
    out.push_str("\n\n");
    push_group(out, run.records);
    out.push_str(" records, ");
    push_group(out, analysis.templates.len() as u64);
    out.push_str(" templates, ");
    push_group(out, run.unparsed);
    out.push_str(" unparsed lines.\n");
    if !analysis.levels.is_empty() {
        out.push_str("\nLevels: ");
        for (index, (name, count)) in analysis.levels.iter().rev().enumerate() {
            if index > 0 {
                out.push_str(", ");
            }
            let _ = write!(out, "{name} ");
            push_group(out, *count);
        }
        out.push('\n');
    }
    warning_lines(out, analysis.warnings);
    let shown = &analysis.templates[..rows.min(analysis.templates.len())];
    out.push_str("\n### Most frequent templates (");
    push_group(out, shown.len() as u64);
    out.push_str(" of ");
    push_group(out, analysis.templates.len() as u64);
    out.push_str(")\n\n");
    for row in shown {
        template_line(out, row, run.records);
    }
}

fn diff_lines(out: &mut String, diff: &DiffInput<'_>, rows: usize) {
    let alerts = diff.new.iter().filter(|row| is_alert(row.level)).count() as u64;
    let _ = write!(out, "## logfold: {}\n\n", run_names(diff.before.name, diff.after.name, NAME_WIDTH));
    if alerts > 0 {
        let _ = write!(out, "**{}.**\n\n", alert_noun(alerts));
    } else {
        out.push_str("**No new WARN+ templates.**\n\n");
    }
    out.push_str("| new | WARN+ | disappeared | changed | unchanged | records |\n|---:|---:|---:|---:|---:|---|\n| ");
    for (index, count) in [diff.new.len() as u64, alerts, diff.disappeared.len() as u64, diff.changed.len() as u64]
        .into_iter()
        .chain([diff.unchanged])
        .enumerate()
    {
        if index > 0 {
            out.push_str(" | ");
        }
        push_group(out, count);
    }
    out.push_str(" | ");
    push_group(out, diff.before.records);
    out.push_str(" -> ");
    push_group(out, diff.after.records);
    out.push_str(" |\n");
    warning_lines(out, diff.warnings);
    let order = alerts_first(diff.new);
    let shown = &order[..rows.min(order.len())];
    out.push_str("\n### New templates (");
    push_group(out, shown.len() as u64);
    out.push_str(" of ");
    push_group(out, diff.new.len() as u64);
    out.push_str(")\n\n");
    for &index in shown {
        entry_line(out, &diff.new[index], "new");
    }
    for (title, kind, entries) in
        [("Changed", "changed", diff.changed), ("Disappeared", "disappeared", diff.disappeared)]
    {
        if entries.is_empty() {
            continue;
        }
        let _ = write!(out, "\n<details><summary>{title} templates (");
        push_group(out, entries.len() as u64);
        out.push_str(")</summary>\n\n");
        for row in &entries[..rows.min(entries.len())] {
            entry_line(out, row, kind);
        }
        out.push_str("\n</details>\n");
    }
}
