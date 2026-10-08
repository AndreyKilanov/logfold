#![allow(missing_docs)]
//! Reading a sample: the counts, the first records and the refusal of an invalid format.

use logfold_core::Level;
use logfold_engine::{EngineError, inspect_sample};
use logfold_io::{FormatConfig, FormatSpec, IoError, parse_iso};

fn plain(multiline: bool, record_start: Option<&str>) -> FormatConfig {
    let spec = FormatSpec::Plain { record_start: record_start.map(String::from) };
    FormatConfig { spec, ts_format: None, multiline }
}

fn app(multiline: bool) -> FormatConfig {
    let spec = FormatSpec::Regex {
        pattern: r"^(?P<ts>\S+) (?P<level>[A-Z]+) (?P<msg>.*)$".into(),
        message_group: Some("msg".into()),
        time_group: Some("ts".into()),
        level_group: Some("level".into()),
    };
    FormatConfig { spec, ts_format: None, multiline }
}

fn micros(text: &str) -> i64 {
    parse_iso(text.as_bytes()).expect("a valid timestamp").micros
}

#[test]
fn plain_lines_are_records_without_time_or_level() {
    let report = inspect_sample(&plain(false, None), b"one\ntwo words\nthree\n", 10).unwrap();
    assert_eq!((report.lines, report.records, report.unparsed), (3, 3, 0));
    assert_eq!(report.no_level, 3);
    assert_eq!(report.levels, [0; 6]);
    assert!(report.first.is_none() && report.last.is_none() && !report.tz_aware);
    let messages: Vec<&str> = report.shown.iter().map(|record| record.message.as_str()).collect();
    assert_eq!(messages, ["one", "two words", "three"]);
}

#[test]
fn a_format_reports_times_and_levels() {
    let sample =
        b"2026-10-04T12:00:05Z ERROR disk full\n2026-10-04T12:00:01Z INFO started\n2026-10-04T12:00:09Z ERROR again\n";
    let report = inspect_sample(&app(false), sample, 10).unwrap();
    assert_eq!(report.records, 3);
    assert_eq!(report.levels[Level::Error.rank()], 2);
    assert_eq!(report.levels[Level::Info.rank()], 1);
    assert_eq!(report.no_level, 0);
    assert_eq!(report.first, Some(micros("2026-10-04T12:00:01Z")));
    assert_eq!(report.last, Some(micros("2026-10-04T12:00:09Z")));
    assert!(report.tz_aware);
    let first = &report.shown[0];
    assert_eq!((first.message.as_str(), first.level, first.lines), ("disk full", Some(Level::Error), 1));
}

#[test]
fn only_the_first_records_are_kept_but_all_are_counted() {
    let sample: String = (0..7).map(|index| format!("line {index}\n")).collect();
    let report = inspect_sample(&plain(false, None), sample.as_bytes(), 2).unwrap();
    assert_eq!(report.shown.len(), 2);
    assert_eq!((report.records, report.lines), (7, 7));
}

#[test]
fn blank_lines_are_never_records() {
    let report = inspect_sample(&plain(false, None), b"a\n\n   \nb\n", 10).unwrap();
    assert_eq!((report.lines, report.records, report.unparsed), (4, 2, 0));
}

#[test]
fn continuation_lines_join_the_record_and_leading_ones_are_unparsed() {
    let sample = b"  at stray.frame\n2026-10-04T12:00:01Z ERROR boom\n  at a.b(C.java:1)\n  at d.e(F.java:2)\n2026-10-04T12:00:02Z INFO ok\n";
    let report = inspect_sample(&app(true), sample, 10).unwrap();
    assert_eq!((report.lines, report.records, report.unparsed), (5, 2, 1));
    assert_eq!(report.shown[0].lines, 3);
    assert!(report.shown[0].message.starts_with("boom\n  at a.b"));
    assert_eq!(report.shown[1].lines, 1);
}

#[test]
fn lines_that_do_not_match_the_pattern_are_unparsed() {
    let report = inspect_sample(&app(false), b"2026-10-04T12:00:01Z INFO fine\nnot a log line\n", 10).unwrap();
    assert_eq!((report.records, report.unparsed), (1, 1));
}

#[test]
fn json_lines_use_their_keys_and_a_plain_line_is_unparsed() {
    let spec = FormatSpec::Json {
        message_keys: vec!["msg".into()],
        time_keys: vec!["time".into()],
        level_keys: vec!["level".into()],
    };
    let config = FormatConfig { spec, ts_format: None, multiline: false };
    let sample = b"{\"msg\":\"hello\",\"time\":\"2026-10-04T12:00:01Z\",\"level\":\"warn\"}\nnot json\n";
    let report = inspect_sample(&config, sample, 10).unwrap();
    assert_eq!((report.records, report.unparsed), (1, 1));
    assert_eq!(report.levels[Level::Warn.rank()], 1);
    assert_eq!(report.shown[0].message, "hello");
}

#[test]
fn invalid_utf8_is_replaced_and_an_empty_sample_is_empty() {
    let report = inspect_sample(&plain(false, None), b"bad \xff byte\n", 10).unwrap();
    assert!(report.shown[0].message.contains('\u{fffd}'));
    let empty = inspect_sample(&plain(false, None), b"", 10).unwrap();
    assert_eq!((empty.lines, empty.records, empty.shown.len()), (0, 0, 0));
}

#[test]
fn an_invalid_pattern_is_a_format_error() {
    let spec = FormatSpec::Regex { pattern: "(".into(), message_group: None, time_group: None, level_group: None };
    let config = FormatConfig { spec, ts_format: None, multiline: false };
    let error = inspect_sample(&config, b"x\n", 10).unwrap_err();
    assert!(matches!(error, EngineError::Io(IoError::Format(_))), "{error}");
}
