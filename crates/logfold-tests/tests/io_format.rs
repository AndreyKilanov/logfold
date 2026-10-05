#![allow(missing_docs)]

use logfold_core::Level;
use logfold_io::*;

fn json_format() -> CompiledFormat {
    CompiledFormat::new(&FormatConfig {
        spec: FormatSpec::Json {
            message_keys: vec!["message".into(), "msg".into()],
            time_keys: vec!["ts".into()],
            level_keys: vec!["level".into()],
        },
        ts_format: None,
        multiline: false,
    })
    .unwrap()
}

#[test]
fn json_extracts_fields() {
    let fmt = json_format();
    let line = br#"{"level":"warning","msg":"disk 90%","ts":"1970-01-01T00:00:02Z"}"#;
    let rec = fmt.parse(line, line.len()).unwrap();
    assert_eq!(&*rec.message, b"disk 90%");
    assert_eq!(rec.timestamp, Some(2_000_000));
    assert_eq!(rec.level, Some(Level::Warn));
    assert!(fmt.parse(b"not json", 8).is_none());
    assert!(fmt.parse(br#"{"other":1}"#, 11).is_none());
}

#[test]
fn regex_groups_and_continuation() {
    let fmt = CompiledFormat::new(&FormatConfig {
        spec: FormatSpec::Regex {
            pattern: r"^(?P<ts>\S+) (?P<lvl>[A-Z]+) (?P<msg>.*)$".into(),
            message_group: Some("msg".into()),
            time_group: Some("ts".into()),
            level_group: Some("lvl".into()),
        },
        ts_format: None,
        multiline: true,
    })
    .unwrap();
    let text = b"1970-01-01T00:00:01Z ERROR boom\n  at frame 1";
    let first = "1970-01-01T00:00:01Z ERROR boom".len();
    let rec = fmt.parse(text, first).unwrap();
    assert_eq!(&*rec.message, b"boom\n  at frame 1");
    assert_eq!(rec.level, Some(Level::Error));
    assert_eq!(rec.timestamp, Some(1_000_000));
    assert!(fmt.starts_record(b"1970-01-01T00:00:01Z INFO ok"));
    assert!(!fmt.starts_record(b"  at frame 1"));
}

#[test]
fn rejects_unknown_group() {
    let result = CompiledFormat::new(&FormatConfig {
        spec: FormatSpec::Regex {
            pattern: "(?P<a>x)".into(),
            message_group: Some("nope".into()),
            time_group: None,
            level_group: None,
        },
        ts_format: None,
        multiline: false,
    });
    assert!(result.is_err());
}
