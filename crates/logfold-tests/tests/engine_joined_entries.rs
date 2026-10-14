#![allow(missing_docs)]

//! Docker `json-file` entries that are pieces of one line are joined into one record, whatever the chunking.

use std::path::PathBuf;

use logfold_core::default_mask_rules;
use logfold_engine::{ExecutionStrategy, MineRequest, MiningConfig, NullObserver, Session, SessionConfig, mine};
use logfold_io::{FormatConfig, FormatSpec};

fn format(join: bool) -> FormatConfig {
    FormatConfig {
        spec: FormatSpec::Json {
            message_keys: vec!["log".into()],
            time_keys: vec!["time".into()],
            level_keys: Vec::new(),
            join_unterminated: join,
        },
        ts_format: None,
        multiline: false,
    }
}

fn request(path: PathBuf, strategy: ExecutionStrategy, join: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path]],
        format: format(join),
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

/// What the lines of a file must give: records, lines and unparsed lines.
struct Expected {
    records: u64,
    lines: u64,
    unparsed: u64,
}

/// A log of `logical` printed lines, each cut into one to four entries; some blank lines, some lines that are not
/// entries, and a last line without a line break.
fn docker_log(logical: usize, seed: usize) -> (String, Expected) {
    let mut text = String::new();
    let mut expected = Expected { records: 0, lines: 0, unparsed: 0 };
    for index in 0..logical {
        let pieces = 1 + (index * 7 + seed) % 4;
        let last = index + 1 == logical;
        for piece in 0..pieces {
            let end = piece + 1 == pieces;
            let tail = if end && !last { "\\n" } else { "" };
            text.push_str(&format!(
                "{{\"log\":\"part {index}.{piece} of line {}{tail}\",\"stream\":\"stdout\",\"time\":\"2026-10-04T12:00:{:02}.000000001Z\"}}\n",
                index % 13,
                (index + piece) % 60
            ));
            expected.lines += 1;
        }
        expected.records += 1;
        if index % 11 == 3 {
            text.push('\n');
            expected.lines += 1;
        }
        if index % 17 == 5 {
            text.push_str("this line is not an entry\n");
            expected.lines += 1;
            expected.unparsed += 1;
        }
    }
    (text, expected)
}

fn write(dir: &tempfile::TempDir, text: &str) -> PathBuf {
    let path = dir.path().join("x-json.log");
    std::fs::write(&path, text).unwrap();
    path
}

#[test]
fn the_pieces_of_a_line_are_one_record_and_the_others_are_not_joined() {
    let dir = tempfile::tempdir().unwrap();
    let text = concat!(
        "{\"log\":\"first \",\"time\":\"2026-10-04T12:00:01Z\"}\n",
        "{\"log\":\"second \",\"time\":\"2026-10-04T12:00:02Z\"}\n",
        "{\"log\":\"third\\n\",\"time\":\"2026-10-04T12:00:03Z\"}\n",
        "{\"log\":\"alone\\r\\n\",\"time\":\"2026-10-04T12:00:04Z\"}\n",
        "{\"log\":\"no break at the end\",\"time\":\"2026-10-04T12:00:05Z\"}\n",
    );
    let path = write(&dir, text);
    let joined = mine(&request(path.clone(), ExecutionStrategy::Sequential, true), &NullObserver).unwrap();
    assert_eq!((joined.runs[0].records, joined.runs[0].lines, joined.runs[0].unparsed), (3, 5, 0));
    let texts: Vec<_> = joined.templates.iter().map(|t| t.text.clone()).collect();
    assert!(texts.contains(&"first second third".to_string()), "{texts:?}");
    assert!(texts.contains(&"alone".to_string()), "{texts:?}");
    let separate = mine(&request(path, ExecutionStrategy::Sequential, false), &NullObserver).unwrap();
    assert_eq!(separate.runs[0].records, 5);
}

#[test]
fn a_line_that_is_not_an_entry_ends_the_pieces_before_it() {
    let dir = tempfile::tempdir().unwrap();
    let text = concat!(
        "{\"log\":\"begun \",\"time\":\"2026-10-04T12:00:01Z\"}\n",
        "garbage\n",
        "{\"log\":\"next\\n\",\"time\":\"2026-10-04T12:00:02Z\"}\n",
    );
    let output = mine(&request(write(&dir, text), ExecutionStrategy::Sequential, true), &NullObserver).unwrap();
    assert_eq!((output.runs[0].records, output.runs[0].lines, output.runs[0].unparsed), (2, 3, 1));
}

fn assert_same_counts(logical: usize, chunk_sizes: &[u64]) {
    for seed in 0..3 {
        let dir = tempfile::tempdir().unwrap();
        let (text, expected) = docker_log(logical, seed);
        let path = write(&dir, &text);
        let sequential = mine(&request(path.clone(), ExecutionStrategy::Sequential, true), &NullObserver).unwrap();
        let run = &sequential.runs[0];
        assert_eq!((run.records, run.lines, run.unparsed), (expected.records, expected.lines, expected.unparsed));
        for &chunk_bytes in chunk_sizes {
            for threads in [1, 3] {
                let strategy = ExecutionStrategy::Chunked { chunk_bytes, threads };
                let chunked = mine(&request(path.clone(), strategy, true), &NullObserver).unwrap();
                let run = &chunked.runs[0];
                assert_eq!(
                    (run.records, run.lines, run.unparsed),
                    (expected.records, expected.lines, expected.unparsed),
                    "seed {seed}, chunks of {chunk_bytes} bytes, {threads} threads"
                );
            }
        }
    }
}

#[test]
fn counts_do_not_depend_on_the_chunk_size_or_the_threads() {
    assert_same_counts(60, &[64, 100, 257, 1000, 4096]);
}

#[test]
fn chunks_of_one_byte_and_a_few_bytes_give_the_same_counts() {
    assert_same_counts(8, &[1, 7]);
}

#[test]
fn a_session_joins_the_pieces_given_in_any_batches() {
    let (text, expected) = docker_log(80, 1);
    let lines: Vec<&[u8]> = text.lines().map(str::as_bytes).collect();
    for batch in [1, 2, 5, 1000] {
        let mut session = Session::new(SessionConfig {
            format: format(true),
            masks: default_mask_rules(),
            mining: MiningConfig::default(),
            initial: None,
        })
        .unwrap();
        let mut mined = 0;
        for part in lines.chunks(batch) {
            mined += session.add_lines(part.iter().copied());
        }
        mined += session.flush();
        let output = session.output();
        assert_eq!(mined, expected.records, "batches of {batch}");
        let run = &output.runs[0];
        assert_eq!((run.records, run.lines, run.unparsed), (expected.records, expected.lines, expected.unparsed));
    }
}
