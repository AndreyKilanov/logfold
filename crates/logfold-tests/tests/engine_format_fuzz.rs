#![allow(missing_docs)]

//! Arbitrary bytes (NUL, bytes that are not UTF-8, CR, long lines) through the format kinds: nothing panics, every
//! non-blank line is in a record or counted as unparsed, and the chunking changes none of the counters.
//!
//! `PROPTEST_CASES` sets the number of cases (40 by default).

use std::path::PathBuf;

use logfold_core::default_mask_rules;
use logfold_engine::{ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, mine};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

const ISO_RECORD: &str = r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}) (?P<lvl>[A-Z]+) (?P<msg>.*)$";

fn formats() -> Vec<(&'static str, FormatConfig)> {
    let json = |join| FormatSpec::Json {
        message_keys: vec!["log".into(), "message".into()],
        time_keys: vec!["time".into()],
        level_keys: vec!["level".into()],
        join_unterminated: join,
    };
    vec![
        ("plain", FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false }),
        (
            "plain with a record start",
            FormatConfig {
                spec: FormatSpec::Plain { record_start: Some(r"^\d{4}-".into()) },
                ts_format: None,
                multiline: true,
            },
        ),
        (
            "regex",
            FormatConfig {
                spec: FormatSpec::Regex {
                    pattern: ISO_RECORD.into(),
                    message_group: Some("msg".into()),
                    time_group: Some("ts".into()),
                    level_group: Some("lvl".into()),
                },
                ts_format: None,
                multiline: false,
            },
        ),
        (
            "regex, multiline",
            FormatConfig {
                spec: FormatSpec::Regex {
                    pattern: ISO_RECORD.into(),
                    message_group: Some("msg".into()),
                    time_group: Some("ts".into()),
                    level_group: Some("lvl".into()),
                },
                ts_format: Some("%Y-%m-%dT%H:%M:%S".into()),
                multiline: true,
            },
        ),
        ("json", FormatConfig { spec: json(false), ts_format: None, multiline: false }),
        ("json, joined", FormatConfig { spec: json(true), ts_format: None, multiline: false }),
    ]
}

/// A line made of the pieces that break parsers: a record start, braces, quotes, NUL, bytes that are not UTF-8.
fn piece() -> impl Strategy<Value = Vec<u8>> {
    prop_oneof![
        3 => Just(b"2026-10-04T10:00:00 ERROR boom".to_vec()),
        2 => Just(b"2026-10-04T10:00:01 INFO ok 12".to_vec()),
        2 => Just(br#"{"log":"piece ","time":"2026-10-04T10:00:02Z"}"#.to_vec()),
        2 => Just(br#"{"log":"end\n","level":"warn"}"#.to_vec()),
        1 => Just(br#"{"message":"x"#.to_vec()),
        1 => Just(b"   at frame 1".to_vec()),
        1 => Just(Vec::new()),
        1 => Just(vec![0u8, 255, 254, 195]),
        1 => Just(vec![b'x'; 300]),
        2 => prop::collection::vec(any::<u8>(), 0..40),
    ]
}

fn log() -> impl Strategy<Value = Vec<u8>> {
    let eol = prop_oneof![3 => Just(b"\n".to_vec()), 1 => Just(b"\r\n".to_vec())];
    (prop::collection::vec(piece(), 0..25), eol, any::<bool>()).prop_map(|(pieces, eol, last)| {
        let mut data = pieces.join(eol.as_slice());
        if last {
            data.extend_from_slice(&eol);
        }
        data
    })
}

fn request(path: PathBuf, format: &FormatConfig, strategy: ExecutionStrategy) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path]],
        format: format.clone(),
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy,
        warm_start: false,
        recount: false,
        initial: None,
        keep_snapshot: false,
        values: None,
    }
}

fn counters(output: &MineOutput) -> (u64, u64, u64) {
    let run = &output.runs[0];
    (run.lines, run.records, run.unparsed)
}

/// Physical lines of the file: the pieces between line feeds, without the empty piece after a last line feed.
fn physical_lines(data: &[u8]) -> u64 {
    let pieces = data.split(|&byte| byte == b'\n').count() as u64;
    if data.is_empty() || data.ends_with(b"\n") { pieces - 1 } else { pieces }
}

fn cases() -> u32 {
    std::env::var("PROPTEST_CASES").ok().and_then(|text| text.parse().ok()).unwrap_or(40)
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(cases()))]

    #[test]
    fn the_chunking_changes_none_of_the_counters(data in log(), chunk_bytes in 1u64..80, threads in 1usize..=4) {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("fuzz.log");
        std::fs::write(&path, &data).unwrap();
        for (name, format) in formats() {
            let whole = mine(&request(path.clone(), &format, ExecutionStrategy::Sequential), &NullObserver).unwrap();
            let parts = mine(
                &request(path.clone(), &format, ExecutionStrategy::Chunked { chunk_bytes, threads }),
                &NullObserver,
            )
            .unwrap();
            prop_assert_eq!(counters(&parts), counters(&whole), "{} in chunks of {} bytes", name, chunk_bytes);
            prop_assert_eq!(whole.runs[0].lines, physical_lines(&data), "{}", name);
            prop_assert_eq!(whole.runs[0].records + whole.runs[0].unparsed <= whole.runs[0].lines, true);
        }
    }
}
