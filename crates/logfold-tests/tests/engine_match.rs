#![allow(missing_docs)]

//! Matching records against a saved miner: nothing is learned, every record is either matched or counted as
//! unmatched, and the result does not depend on the strategy.

use std::io::Write;
use std::path::{Path, PathBuf};

use logfold_core::{MinerSnapshot, default_mask_rules};
use logfold_engine::{
    EngineError, ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, match_records, mine,
};
use logfold_io::{FormatConfig, FormatSpec};

fn write_log(dir: &tempfile::TempDir, name: &str, range: std::ops::Range<usize>, extra: &[String]) -> PathBuf {
    let path = dir.path().join(name);
    let mut file = std::fs::File::create(&path).unwrap();
    for n in range {
        match n % 5 {
            0 => writeln!(file, "INFO user u{} logged in from 10.0.{}.{}", n % 97, n % 8, n % 250),
            1 => writeln!(file, "WARN disk usage {}% on /dev/sda{}", 50 + n % 40, n % 3),
            2 => writeln!(file, "ERROR request {} failed with status {}", n, 500 + n % 4),
            3 => writeln!(file, "INFO cache miss for key k{}", n % 1013),
            _ => writeln!(file, "INFO job {} finished", n),
        }
        .unwrap();
    }
    for line in extra {
        writeln!(file, "{line}").unwrap();
    }
    path
}

fn request(path: &Path, strategy: ExecutionStrategy, initial: Option<MinerSnapshot>, keep: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy,
        warm_start: false,
        recount: false,
        initial,
        keep_snapshot: keep,
    }
}

fn saved(path: &Path) -> MinerSnapshot {
    mine(&request(path, ExecutionStrategy::Sequential, None, true), &NullObserver).unwrap().snapshot.unwrap()
}

fn chunked(threads: usize) -> ExecutionStrategy {
    ExecutionStrategy::Chunked { chunk_bytes: 4 * 1024, threads }
}

fn counts(output: &MineOutput) -> Vec<(String, u64)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs[0].count)).collect()
}

fn matched(output: &MineOutput) -> u64 {
    output.templates.iter().map(|t| t.runs[0].count).sum()
}

fn unmatched(output: &MineOutput) -> u64 {
    output.unmatched.as_ref().unwrap()[0].iter().map(|(_, records)| records).sum()
}

fn unknown_lines() -> Vec<String> {
    let long: Vec<String> = (0..40).map(|i| format!("w{}", i % 3)).collect();
    vec![long.join(" "), long.join(" "), "a b".to_string()]
}

#[test]
fn the_records_of_the_trained_log_all_match_and_give_the_counts_of_a_recount() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, "a.log", 0..3000, &[]);
    let state = saved(&path);
    let output =
        match_records(&request(&path, ExecutionStrategy::Sequential, Some(state.clone()), false), &NullObserver)
            .unwrap();
    assert_eq!(output.runs[0].records, 3000);
    assert_eq!(matched(&output), 3000);
    assert_eq!(output.unmatched, Some(vec![Vec::new()]));
    let mut recounting = request(&path, ExecutionStrategy::Sequential, Some(state), false);
    recounting.recount = true;
    assert_eq!(counts(&output), counts(&mine(&recounting, &NullObserver).unwrap()));
}

#[test]
fn records_of_another_shape_are_counted_by_their_length() {
    let dir = tempfile::tempdir().unwrap();
    let trained = write_log(&dir, "a.log", 0..1000, &[]);
    let state = saved(&trained);
    let fresh = write_log(&dir, "b.log", 1000..1500, &unknown_lines());
    let output =
        match_records(&request(&fresh, ExecutionStrategy::Sequential, Some(state), false), &NullObserver).unwrap();
    assert_eq!(output.unmatched, Some(vec![vec![(2, 1), (40, 2)]]));
    assert_eq!(matched(&output) + unmatched(&output), output.runs[0].records);
    assert_eq!(output.runs[0].records, 503);
    assert!(!output.runs[0].overflowed, "the unmatched records are not templates");
    assert!(output.templates.iter().all(|t| !t.text.starts_with("<*> <*>")));
}

#[test]
fn matching_does_not_change_the_state_and_returns_no_snapshot() {
    let dir = tempfile::tempdir().unwrap();
    let trained = write_log(&dir, "a.log", 0..1000, &[]);
    let state = saved(&trained);
    let before = state.clone();
    let fresh = write_log(&dir, "b.log", 1000..1300, &unknown_lines());
    let output =
        match_records(&request(&fresh, ExecutionStrategy::Sequential, Some(state.clone()), true), &NullObserver)
            .unwrap();
    assert!(output.snapshot.is_none());
    assert_eq!(state, before);
    let again =
        match_records(&request(&fresh, ExecutionStrategy::Sequential, Some(state), false), &NullObserver).unwrap();
    assert_eq!(counts(&again), counts(&output), "the same state gives the same answer twice");
}

#[test]
fn the_strategy_and_the_threads_do_not_change_the_answer() {
    let dir = tempfile::tempdir().unwrap();
    let trained = write_log(&dir, "a.log", 0..1000, &[]);
    let state = saved(&trained);
    let fresh = write_log(&dir, "b.log", 1000..9000, &unknown_lines());
    let one = match_records(&request(&fresh, ExecutionStrategy::Sequential, Some(state.clone()), false), &NullObserver)
        .unwrap();
    for threads in [1, 2, 5] {
        let many =
            match_records(&request(&fresh, chunked(threads), Some(state.clone()), false), &NullObserver).unwrap();
        assert_eq!(many.metrics.strategy, "chunked");
        assert!(many.metrics.chunks > 1, "the log must be cut into chunks");
        assert_eq!(counts(&many), counts(&one), "{threads} threads");
        assert_eq!(many.unmatched, one.unmatched, "{threads} threads");
        assert_eq!(many.runs[0].records, one.runs[0].records, "{threads} threads");
        assert_eq!(many.runs[0].lines, one.runs[0].lines, "{threads} threads");
    }
}

#[test]
fn matching_without_a_state_is_a_config_error() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, "a.log", 0..10, &[]);
    let error = match_records(&request(&path, ExecutionStrategy::Sequential, None, false), &NullObserver).unwrap_err();
    assert!(matches!(&error, EngineError::Config(message) if message.contains("saved state")), "{error}");
}

#[test]
fn a_state_mined_with_other_parameters_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, "a.log", 0..100, &[]);
    let state = saved(&path);
    let mut other = request(&path, ExecutionStrategy::Sequential, Some(state), false);
    other.mining.depth = 6;
    let error = match_records(&other, &NullObserver).unwrap_err();
    assert!(matches!(&error, EngineError::Config(message) if message.contains("other parameters")), "{error}");
}
