#![allow(missing_docs)]

use std::io::Write;
use std::path::PathBuf;

use logfold_core::default_mask_rules;
use logfold_engine::{EngineError, ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, mine};
use logfold_io::{FormatConfig, FormatSpec, TimeWindow, parse_iso};

const SECOND: i64 = 1_000_000;
const RECORDS: usize = 4000;

/// Every seventh record has a time that cannot be parsed, so a bounded window cannot place it.
fn is_untimed(index: usize) -> bool {
    index % 7 == 3
}

fn write_log(dir: &tempfile::TempDir) -> PathBuf {
    let path = dir.path().join("timed.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for i in 0..RECORDS {
        let stamp = if is_untimed(i) {
            "no-time".to_string()
        } else {
            format!("2026-10-04T{:02}:{:02}:{:02}Z", i / 3600, (i / 60) % 60, i % 60)
        };
        match i % 4 {
            0 => writeln!(file, "{stamp} INFO user u{} logged in from 10.0.{}.{}", i % 97, i % 8, i % 250),
            1 => writeln!(file, "{stamp} WARN disk usage {}% on /dev/sda{}", 50 + i % 40, i % 3),
            2 => writeln!(file, "{stamp} ERROR request {i} failed with status {}", 500 + i % 4),
            _ => writeln!(file, "{stamp} INFO cache miss for key k{}", i % 1013),
        }
        .unwrap();
    }
    path
}

fn base() -> i64 {
    parse_iso(b"2026-10-04T00:00:00Z").unwrap().micros
}

fn at(second: usize) -> i64 {
    base() + second as i64 * SECOND
}

fn request(runs: Vec<Vec<PathBuf>>, windows: Vec<TimeWindow>, strategy: ExecutionStrategy) -> MineRequest {
    MineRequest {
        runs,
        windows,
        format: FormatConfig {
            spec: FormatSpec::Regex {
                pattern: r"^(?P<ts>\S+) (?P<lvl>[A-Z]+) (?P<msg>.*)$".into(),
                message_group: Some("msg".into()),
                time_group: Some("ts".into()),
                level_group: Some("lvl".into()),
            },
            ts_format: None,
            multiline: false,
        },
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy,
        warm_start: false,
        recount: true,
        initial: None,
        keep_snapshot: false,
    }
}

fn summary(output: &MineOutput) -> Vec<(String, Vec<u64>)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs.iter().map(|r| r.count).collect())).collect()
}

fn inside(from: usize, to: usize) -> u64 {
    (from..to).filter(|&i| !is_untimed(i)).count() as u64
}

#[test]
fn a_window_keeps_only_the_records_inside_it() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let window = TimeWindow { since: Some(at(1000)), until: Some(at(2500)) };
    let output = mine(&request(vec![vec![path]], vec![window], ExecutionStrategy::Sequential), &NullObserver).unwrap();
    let run = &output.runs[0];
    assert_eq!(run.records, inside(1000, 2500));
    let untimed = (0..RECORDS).filter(|&i| is_untimed(i)).count() as u64;
    assert_eq!(run.untimed, untimed);
    assert_eq!(run.records + run.out_of_range + run.untimed, RECORDS as u64);
    assert_eq!(run.lines, RECORDS as u64);
    let mined: u64 = output.templates.iter().map(|t| t.total()).sum();
    assert_eq!(mined, run.records);
}

#[test]
fn without_a_window_nothing_is_left_out_and_untimed_records_stay() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let output = mine(&request(vec![vec![path]], Vec::new(), ExecutionStrategy::Sequential), &NullObserver).unwrap();
    assert_eq!(output.runs[0].records, RECORDS as u64);
    assert_eq!((output.runs[0].out_of_range, output.runs[0].untimed), (0, 0));
}

#[test]
fn an_open_window_equals_no_window() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let none =
        mine(&request(vec![vec![path.clone()]], Vec::new(), ExecutionStrategy::Sequential), &NullObserver).unwrap();
    let open =
        mine(&request(vec![vec![path]], vec![TimeWindow::default()], ExecutionStrategy::Sequential), &NullObserver)
            .unwrap();
    assert_eq!(summary(&none), summary(&open));
    assert_eq!(open.runs[0].records, RECORDS as u64);
}

#[test]
fn chunked_and_sequential_agree_with_a_window() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let window = TimeWindow { since: Some(at(700)), until: Some(at(3100)) };
    let sequential =
        mine(&request(vec![vec![path.clone()]], vec![window], ExecutionStrategy::Sequential), &NullObserver).unwrap();
    for threads in [1, 4] {
        let strategy = ExecutionStrategy::Chunked { chunk_bytes: 2048, threads };
        let chunked = mine(&request(vec![vec![path.clone()]], vec![window], strategy), &NullObserver).unwrap();
        assert!(chunked.metrics.chunks > 1);
        let (a, b) = (&sequential.runs[0], &chunked.runs[0]);
        assert_eq!((a.records, a.out_of_range, a.untimed, a.lines), (b.records, b.out_of_range, b.untimed, b.lines));
        let mined: u64 = chunked.templates.iter().map(|t| t.total()).sum();
        assert_eq!(mined, b.records);
    }
}

#[test]
fn two_windows_of_one_file_split_it_into_two_runs() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let split = at(2000);
    let windows = vec![TimeWindow { since: None, until: Some(split) }, TimeWindow { since: Some(split), until: None }];
    let output =
        mine(&request(vec![vec![path.clone()], vec![path]], windows, ExecutionStrategy::Sequential), &NullObserver)
            .unwrap();
    let (before, after) = (&output.runs[0], &output.runs[1]);
    assert_eq!(before.records, inside(0, 2000));
    assert_eq!(after.records, inside(2000, RECORDS));
    assert_eq!(before.records + after.records + before.untimed, RECORDS as u64);
    assert_eq!(before.out_of_range, after.records);
    assert_eq!(after.out_of_range, before.records);
    for template in &output.templates {
        assert!(template.runs[0].count + template.runs[1].count > 0);
    }
}

#[test]
fn a_window_that_matches_nothing_gives_an_empty_run() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let window = TimeWindow { since: Some(at(86_000)), until: None };
    let output = mine(&request(vec![vec![path]], vec![window], ExecutionStrategy::Sequential), &NullObserver).unwrap();
    assert_eq!(output.runs[0].records, 0);
    assert!(output.templates.is_empty());
}

#[test]
fn the_number_of_windows_must_match_the_number_of_runs() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir);
    let windows = vec![TimeWindow::default(), TimeWindow::default()];
    let result = mine(&request(vec![vec![path]], windows, ExecutionStrategy::Sequential), &NullObserver);
    assert!(matches!(result, Err(EngineError::Config(_))));
}
