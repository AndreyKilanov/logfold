//! `prometheus`: gauges in the text exposition format.

use std::fmt::Write as _;

use super::text::push_label_value;
use super::{AnalysisInput, DiffInput, ReportRow, ReportSubject, is_alert};

const LABEL_WIDTH: usize = 120;
const ID_WIDTH: usize = 64;

/// Write the header of a family, let `write` add its samples and drop the header again when there are none.
fn family(out: &mut String, name: &str, help: &str, write: impl FnOnce(&mut String)) {
    let start = out.len();
    let _ = write!(out, "# HELP {name} {help}\n# TYPE {name} gauge\n");
    let body = out.len();
    write(out);
    if out.len() == body {
        out.truncate(start);
    }
}

fn plain(out: &mut String, name: &str, value: u64) {
    let _ = writeln!(out, "{name} {value}");
}

fn labelled(out: &mut String, name: &str, key: &str, text: &str, value: u64) {
    let _ = write!(out, "{name}{{{key}=\"");
    push_label_value(out, text, ID_WIDTH);
    let _ = writeln!(out, "\"}} {value}");
}

/// Append `id="..",level="..",template=".."` of a row.
fn template_labels(out: &mut String, row: &ReportRow<'_>) {
    out.push_str("id=\"");
    push_label_value(out, row.id, ID_WIDTH);
    out.push('"');
    if let Some(level) = row.level {
        out.push_str(",level=\"");
        push_label_value(out, level, ID_WIDTH);
        out.push('"');
    }
    out.push_str(",template=\"");
    push_label_value(out, row.text, LABEL_WIDTH);
    out.push('"');
}

fn analysis_text(out: &mut String, analysis: &AnalysisInput<'_>, top: usize) {
    let run = &analysis.run;
    family(out, "logfold_records", "Records parsed from the log.", |body| plain(body, "logfold_records", run.records));
    family(out, "logfold_unparsed_lines", "Lines that no record claimed.", |body| {
        plain(body, "logfold_unparsed_lines", run.unparsed);
    });
    family(out, "logfold_templates", "Distinct templates.", |body| {
        plain(body, "logfold_templates", analysis.templates.len() as u64);
    });
    family(out, "logfold_level_records", "Records per log level.", |body| {
        for (name, count) in analysis.levels {
            labelled(body, "logfold_level_records", "level", name, *count);
        }
    });
    family(out, "logfold_template_records", "Records of the most frequent templates.", |body| {
        for row in &analysis.templates[..top.min(analysis.templates.len())] {
            body.push_str("logfold_template_records{");
            template_labels(body, row);
            let _ = writeln!(body, "}} {}", row.after);
        }
    });
}

fn diff_text(out: &mut String, diff: &DiffInput<'_>, top: usize) {
    let alerts = diff.new.iter().filter(|row| is_alert(row.level)).count() as u64;
    family(out, "logfold_diff_records", "Records of each run.", |body| {
        labelled(body, "logfold_diff_records", "side", "before", diff.before.records);
        labelled(body, "logfold_diff_records", "side", "after", diff.after.records);
    });
    family(out, "logfold_diff_templates", "Templates by what changed between the runs.", |body| {
        for (change, count) in [
            ("new", diff.new.len() as u64),
            ("disappeared", diff.disappeared.len() as u64),
            ("changed", diff.changed.len() as u64),
            ("unchanged", diff.unchanged),
        ] {
            labelled(body, "logfold_diff_templates", "change", change, count);
        }
    });
    family(out, "logfold_diff_new_alerts", "New templates at WARN or above.", |body| {
        plain(body, "logfold_diff_new_alerts", alerts);
    });
    family(out, "logfold_diff_template_records", "Records of the listed templates in each run.", |body| {
        let mut labels = String::new();
        for (change, rows) in [("new", diff.new), ("changed", diff.changed), ("disappeared", diff.disappeared)] {
            for row in &rows[..top.min(rows.len())] {
                labels.clear();
                let _ = write!(labels, "change=\"{change}\",");
                template_labels(&mut labels, row);
                let _ = writeln!(body, "logfold_diff_template_records{{{labels},side=\"before\"}} {}", row.before);
                let _ = writeln!(body, "logfold_diff_template_records{{{labels},side=\"after\"}} {}", row.after);
            }
        }
    });
}

/// Render `subject` as Prometheus gauges. `top` is the number of templates that get a series of their own, per section
/// for a diff. The levels of an analysis are written in the order they are given.
pub fn prometheus(subject: &ReportSubject<'_>, top: usize) -> String {
    let mut out = String::new();
    match subject {
        ReportSubject::Analysis(analysis) => analysis_text(&mut out, analysis, top),
        ReportSubject::Diff(diff) => diff_text(&mut out, diff, top),
    }
    if out.is_empty() {
        out.push('\n');
    }
    out
}
