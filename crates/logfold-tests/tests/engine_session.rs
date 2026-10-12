#![allow(missing_docs)]

//! A live mining session: the records that it takes give the result of mining the same records from a file, a
//! multi-line record waits for the next record or a flush, and a saved state can be continued.

use std::path::{Path, PathBuf};

use logfold_core::{MAX_EXAMPLE_BYTES, MinerSnapshot, default_mask_rules};
use logfold_engine::{
    EngineError, ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, Session, SessionConfig, mine,
};
use logfold_io::{FormatConfig, FormatSpec, MAX_RECORD_BYTES};

const LEVELS: [&str; 4] = ["INFO", "WARN", "ERROR", "DEBUG"];

fn regex_format() -> FormatConfig {
    FormatConfig {
        spec: FormatSpec::Regex {
            pattern: r"^(?P<ts>\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ) (?P<lvl>[A-Z]+) (?P<msg>.*)$".into(),
            message_group: Some("msg".into()),
            time_group: Some("ts".into()),
            level_group: Some("lvl".into()),
        },
        ts_format: None,
        multiline: false,
    }
}

fn traces_format() -> FormatConfig {
    FormatConfig {
        spec: FormatSpec::Plain { record_start: Some(r"^\d{4}-".to_string()) },
        ts_format: None,
        multiline: true,
    }
}

fn log_lines(count: usize) -> Vec<String> {
    (0..count)
        .map(|n| {
            let message = match n % 4 {
                0 => format!("user u{} logged in from 10.0.{}.{}", n % 97, n % 8, n % 250),
                1 => format!("disk usage {}% on /dev/sda{}", 50 + n % 40, n % 3),
                2 => format!("request {} failed with status {}", n, 500 + n % 4),
                _ => format!("job {} finished", n),
            };
            format!("2026-01-01T00:{:02}:{:02}Z {} {}", n / 60 % 60, n % 60, LEVELS[n % 4], message)
        })
        .collect()
}

fn trace_lines(count: usize) -> Vec<String> {
    let mut lines = Vec::new();
    for n in 0..count {
        lines.push(format!("2026-01-01 failure {} in module m{}", n, n % 3));
        for frame in 0..(n % 3) {
            lines.push(format!("  at frame {frame} of call {n}"));
        }
    }
    lines
}

fn write_log(dir: &tempfile::TempDir, lines: &[String]) -> PathBuf {
    let path = dir.path().join("a.log");
    std::fs::write(&path, lines.join("\n") + "\n").unwrap();
    path
}

fn request(path: &Path, format: FormatConfig, initial: Option<MinerSnapshot>, keep: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format,
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy: ExecutionStrategy::Sequential,
        warm_start: false,
        recount: false,
        initial,
        keep_snapshot: keep,
    }
}

fn config(format: FormatConfig, initial: Option<MinerSnapshot>) -> SessionConfig {
    SessionConfig { format, masks: default_mask_rules(), mining: MiningConfig::default(), initial }
}

fn open(format: FormatConfig) -> Session {
    Session::new(config(format, None)).unwrap()
}

fn feed_lines(session: &mut Session, lines: &[String], batch: usize) {
    for part in lines.chunks(batch) {
        session.add_lines(part.iter().map(|line| line.as_bytes()));
    }
    session.flush();
}

type Row = (String, u64, Option<i64>, Option<i64>, Vec<u64>, Option<Box<[u8]>>);

fn rows(output: &MineOutput) -> Vec<Row> {
    output
        .templates
        .iter()
        .map(|t| {
            let stats = &t.runs[0];
            (
                t.text.clone(),
                stats.count,
                stats.has_time().then_some(stats.first),
                stats.has_time().then_some(stats.last),
                stats.levels.to_vec(),
                stats.example.clone(),
            )
        })
        .collect()
}

fn counters(output: &MineOutput) -> (u64, u64, u64) {
    let run = &output.runs[0];
    (run.lines, run.records, run.unparsed)
}

#[test]
fn the_lines_of_a_log_give_the_result_of_mining_the_file() {
    let dir = tempfile::tempdir().unwrap();
    let lines = log_lines(2000);
    let path = write_log(&dir, &lines);
    let expected = mine(&request(&path, regex_format(), None, false), &NullObserver).unwrap();
    for batch in [1, 7, 333, 5000] {
        let mut session = open(regex_format());
        feed_lines(&mut session, &lines, batch);
        let output = session.output();
        assert_eq!(rows(&output), rows(&expected), "batch of {batch}");
        assert_eq!(counters(&output), counters(&expected), "batch of {batch}");
        assert_eq!(output.runs[0].tz_aware, expected.runs[0].tz_aware);
    }
}

#[test]
fn the_snapshot_of_a_session_is_the_snapshot_of_the_file_run() {
    let dir = tempfile::tempdir().unwrap();
    let lines = log_lines(1500);
    let path = write_log(&dir, &lines);
    let expected = mine(&request(&path, regex_format(), None, true), &NullObserver).unwrap().snapshot.unwrap();
    let mut session = open(regex_format());
    feed_lines(&mut session, &lines, 64);
    assert_eq!(session.snapshot(), expected);
}

#[test]
fn a_multi_line_record_stays_open_until_the_next_record_or_a_flush() {
    let mut session = open(traces_format());
    let mined = session.add_lines(["2026-01-01 boom".as_bytes(), b"  at frame 1", b"  at frame 2"]);
    assert_eq!(mined, 0);
    assert_eq!(session.output().runs[0].records, 0);
    assert_eq!(session.add_lines([b"2026-01-01 next".as_slice()]), 1);
    assert_eq!(session.flush(), 1);
    assert_eq!(session.flush(), 0);
    assert_eq!(session.output().runs[0].records, 2);
}

#[test]
fn a_multi_line_log_fed_in_batches_gives_the_result_of_mining_the_file() {
    let dir = tempfile::tempdir().unwrap();
    let lines = trace_lines(400);
    let path = write_log(&dir, &lines);
    let expected = mine(&request(&path, traces_format(), None, false), &NullObserver).unwrap();
    for batch in [1, 2, 5, 1000] {
        let mut session = open(traces_format());
        feed_lines(&mut session, &lines, batch);
        let output = session.output();
        assert_eq!(rows(&output), rows(&expected), "batch of {batch}");
        assert_eq!(counters(&output), counters(&expected), "batch of {batch}");
    }
}

#[test]
fn whole_records_give_the_result_of_the_lines_that_form_them() {
    let lines = trace_lines(300);
    let mut by_lines = open(traces_format());
    feed_lines(&mut by_lines, &lines, 4);
    let mut records: Vec<String> = Vec::new();
    for line in &lines {
        match records.last_mut() {
            Some(last) if line.starts_with(' ') => {
                last.push('\n');
                last.push_str(line);
            }
            _ => records.push(line.clone()),
        }
    }
    let mut by_records = open(traces_format());
    assert_eq!(by_records.add_records(records.iter().map(|record| record.as_bytes())), 300);
    assert_eq!(rows(&by_records.output()), rows(&by_lines.output()));
}

#[test]
fn blank_lines_are_lines_and_a_line_the_format_rejects_is_unparsed() {
    let mut session = open(regex_format());
    let mined = session.add_lines(["".as_bytes(), b"   ", b"not a log line", b"2026-01-01T00:00:01Z INFO ok\r\n"]);
    assert_eq!(mined, 1);
    assert_eq!(counters(&session.output()), (4, 1, 1));
}

#[test]
fn a_record_is_cut_at_the_limit_and_bytes_are_counted_after_the_cut() {
    let mut session =
        open(FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false });
    let long = "word ".repeat(MAX_RECORD_BYTES / 5 + 100);
    assert_eq!(session.add_records([long.as_bytes()]), 1);
    let output = session.output();
    assert_eq!(output.runs[0].bytes, MAX_RECORD_BYTES as u64);
    assert!(output.templates[0].runs[0].example.as_ref().unwrap().len() <= MAX_EXAMPLE_BYTES);
}

#[test]
fn new_templates_are_reported_once_in_the_order_they_were_created() {
    let mut session = open(regex_format());
    assert!(session.take_new_templates().is_empty());
    session.add_lines(["2026-01-01T00:00:01Z INFO first thing happened".as_bytes()]);
    session.add_lines(["2026-01-01T00:00:02Z INFO first thing happened".as_bytes()]);
    assert_eq!(session.take_new_templates(), ["first thing happened"]);
    assert!(session.take_new_templates().is_empty());
    session.add_lines(["2026-01-01T00:00:03Z ERROR a different thing broke down".as_bytes()]);
    assert_eq!(session.take_new_templates(), ["a different thing broke down"]);
}

#[test]
fn a_session_continues_a_saved_state_and_counts_only_its_own_records() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, &log_lines(1000));
    let state = mine(&request(&path, regex_format(), None, true), &NullObserver).unwrap().snapshot.unwrap();
    let mut session = Session::new(config(regex_format(), Some(state))).unwrap();
    session.add_lines([
        "2026-02-01T00:00:01Z INFO job 5 finished".as_bytes(),
        b"2026-02-01T00:00:02Z ERROR the disk caught fire and burned down",
    ]);
    let output = session.output();
    assert_eq!(output.runs[0].records, 2);
    let total: u64 = output.templates.iter().map(|t| t.total()).sum();
    assert_eq!(total, 2);
    assert_eq!(session.take_new_templates(), ["the disk caught fire and burned down"]);
}

#[test]
fn a_state_mined_with_other_parameters_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, &log_lines(50));
    let state = mine(&request(&path, regex_format(), None, true), &NullObserver).unwrap().snapshot.unwrap();
    let mut other = config(regex_format(), Some(state));
    other.mining.depth = 5;
    assert!(matches!(Session::new(other), Err(EngineError::Config(_))));
}

#[test]
fn an_invalid_format_or_parameter_is_refused() {
    let mut bad = config(regex_format(), None);
    bad.mining.sim_th = 2.0;
    assert!(Session::new(bad).is_err());
    let broken = FormatConfig {
        spec: FormatSpec::Regex { pattern: "(".into(), message_group: None, time_group: None, level_group: None },
        ts_format: None,
        multiline: false,
    };
    assert!(Session::new(config(broken, None)).is_err());
}
