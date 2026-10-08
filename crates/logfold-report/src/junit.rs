//! `junit`: a diff as JUnit XML.

use std::fmt::Write as _;

use super::text::{push_escaped_xml, push_group, push_share, xml_text};
use super::{DiffInput, ReportRow, is_alert};

fn push_attribute(out: &mut String, name: &str, value: &str) {
    let _ = write!(out, " {name}=\"");
    push_escaped_xml(out, value, true);
    out.push('"');
}

fn test_case(out: &mut String, row: &ReportRow<'_>, run_records: u64) {
    let level = row.level.unwrap_or("none");
    let id: String = row.id.chars().take(8).collect();
    out.push_str("    <testcase");
    push_attribute(out, "classname", &format!("logfold.new.{level}"));
    push_attribute(out, "name", &format!("{} [{id}]", xml_text(row.text, 200, false)));
    out.push_str(" time=\"0\"");
    if !is_alert(row.level) {
        out.push_str(" />\n");
        return;
    }
    out.push_str(">\n      <failure");
    let mut message = format!("new {level} template, ");
    push_group(&mut message, row.after);
    message.push_str(" records");
    push_attribute(out, "message", &message);
    push_attribute(out, "type", level);
    out.push('>');
    let mut body = format!("template: {}\nrecords: ", xml_text(row.text, 500, false));
    push_group(&mut body, row.after);
    body.push_str(" (");
    push_share(&mut body, row.after, run_records);
    let _ = write!(body, " of the run)\nfirst seen: {}\nlast seen: {}", row.first_seen, row.last_seen);
    push_escaped_xml(out, &body, false);
    out.push_str("</failure>\n    </testcase>\n");
}

/// Render `diff` as JUnit XML: every new WARN+ template is a failed test case, and up to `top` new templates below
/// WARN are passing cases. A diff without any of them holds one passing case, so the report is never empty.
pub fn junit(diff: &DiffInput<'_>, top: usize) -> String {
    let alerts: Vec<&ReportRow<'_>> = diff.new.iter().filter(|row| is_alert(row.level)).collect();
    let quiet: Vec<&ReportRow<'_>> = diff.new.iter().filter(|row| !is_alert(row.level)).take(top).collect();
    let tests = (alerts.len() + quiet.len()).max(1);
    let mut out = String::with_capacity(512 + 400 * (alerts.len() + quiet.len()));
    let _ = write!(
        out,
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<testsuites>\n  <testsuite name=\"logfold\" tests=\"{tests}\" \
         failures=\"{}\" errors=\"0\" skipped=\"0\" time=\"0\">\n    <properties>\n",
        alerts.len()
    );
    let properties = [
        ("before", xml_text(diff.before.name, 200, true)),
        ("after", xml_text(diff.after.name, 200, true)),
        ("new_templates", diff.new.len().to_string()),
        ("disappeared_templates", diff.disappeared.len().to_string()),
        ("changed_templates", diff.changed.len().to_string()),
        ("unchanged_templates", diff.unchanged.to_string()),
    ];
    for (name, value) in properties {
        out.push_str("      <property");
        push_attribute(&mut out, "name", name);
        push_attribute(&mut out, "value", &value);
        out.push_str(" />\n");
    }
    out.push_str("    </properties>\n");
    for row in alerts.iter().chain(&quiet) {
        test_case(&mut out, row, diff.after.records);
    }
    if alerts.is_empty() && quiet.is_empty() {
        out.push_str("    <testcase classname=\"logfold.new\" name=\"no new templates\" time=\"0\" />\n");
    }
    out.push_str("  </testsuite>\n</testsuites>\n");
    out
}
