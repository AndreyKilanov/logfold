#![allow(missing_docs)]

//! Checking a log against a saved state: what is known is matched as by `match_records`, and the records that fit no
//! template form the new templates, which are the templates of mining them alone.

use std::io::Write;
use std::path::{Path, PathBuf};

use logfold_core::{MinerSnapshot, OnFull, default_mask_rules};
use logfold_engine::{
    EngineError, ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, check_records, match_records,
    mine,
};
use logfold_io::{FormatConfig, FormatSpec};

fn known_lines(range: std::ops::Range<usize>) -> Vec<String> {
    range
        .map(|n| match n % 5 {
            0 => format!("INFO user u{} logged in from 10.0.{}.{}", n % 97, n % 8, n % 250),
            1 => format!("WARN disk usage {}% on /dev/sda{}", 50 + n % 40, n % 3),
            2 => format!("ERROR request {} failed with status {}", n, 500 + n % 4),
            3 => format!("INFO cache miss for key k{}", n % 1013),
            _ => format!("INFO job {} finished", n),
        })
        .collect()
}

fn unknown_lines() -> Vec<String> {
    let mut lines: Vec<String> =
        (0..6).map(|n| format!("FATAL kernel panic on node n{n} while mounting volume")).collect();
    lines.extend((0..4).map(|n| format!("ERROR certificate expired for host h{n} aborting handshake now please")));
    lines
}

fn write_log(dir: &tempfile::TempDir, name: &str, lines: &[String]) -> PathBuf {
    let path = dir.path().join(name);
    let mut file = std::fs::File::create(&path).unwrap();
    for line in lines {
        writeln!(file, "{line}").unwrap();
    }
    path
}

fn request(path: &Path, initial: Option<MinerSnapshot>, keep: bool, on_full: OnFull) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningConfig { on_full, ..MiningConfig::default() },
        strategy: ExecutionStrategy::Sequential,
        warm_start: false,
        recount: false,
        initial,
        keep_snapshot: keep,
    }
}

fn saved(path: &Path) -> MinerSnapshot {
    mine(&request(path, None, true, OnFull::Pool), &NullObserver).unwrap().snapshot.unwrap()
}

fn counts(templates: &[logfold_core::FrozenTemplate]) -> Vec<(String, u64)> {
    templates.iter().map(|t| (t.text.clone(), t.runs[0].count)).collect()
}

fn unmatched(output: &MineOutput) -> u64 {
    output.unmatched.as_ref().unwrap()[0].iter().map(|(_, records)| records).sum()
}

#[test]
fn a_log_checked_against_its_own_state_has_nothing_new() {
    let dir = tempfile::tempdir().unwrap();
    let lines = known_lines(0..600);
    let log = write_log(&dir, "good.log", &lines);
    let state = saved(&log);

    let output = check_records(&request(&log, Some(state), false, OnFull::Pool), &NullObserver).unwrap();
    let check = output.check.as_ref().unwrap();

    assert!(check.new_templates.is_empty());
    assert_eq!(unmatched(&output), 0);
    assert_eq!(output.runs[0].records, 600);
    assert_eq!(counts(&check.model), counts(&output.templates));
    assert_eq!(check.model.iter().map(|t| t.runs[0].count).sum::<u64>(), 600);
}

#[test]
fn the_records_that_fit_nothing_form_the_new_templates_of_mining_them_alone() {
    let dir = tempfile::tempdir().unwrap();
    let good = write_log(&dir, "good.log", &known_lines(0..600));
    let state = saved(&good);
    let extra = unknown_lines();
    let mut lines = known_lines(600..900);
    lines.splice(100..100, extra.clone());
    let current = write_log(&dir, "current.log", &lines);

    let output = check_records(&request(&current, Some(state.clone()), false, OnFull::Pool), &NullObserver).unwrap();
    let check = output.check.as_ref().unwrap();
    let matched_only = match_records(&request(&current, Some(state), false, OnFull::Pool), &NullObserver).unwrap();

    assert_eq!(counts(&output.templates), counts(&matched_only.templates), "the known part is the match");
    assert_eq!(output.unmatched, matched_only.unmatched);
    assert_eq!(unmatched(&output), extra.len() as u64);

    let alone = write_log(&dir, "alone.log", &extra);
    let expected = mine(&request(&alone, None, false, OnFull::Pool), &NullObserver).unwrap();
    assert_eq!(counts(&check.new_templates), counts(&expected.templates));
    assert_eq!(check.new_templates.len(), 2);
}

#[test]
fn a_new_template_is_not_a_template_of_the_model() {
    let dir = tempfile::tempdir().unwrap();
    let good = write_log(&dir, "good.log", &known_lines(0..600));
    let state = saved(&good);
    let mut lines = known_lines(0..100);
    lines.extend(unknown_lines());
    let current = write_log(&dir, "current.log", &lines);

    let output = check_records(&request(&current, Some(state), false, OnFull::Pool), &NullObserver).unwrap();
    let check = output.check.as_ref().unwrap();

    let known: std::collections::HashSet<&str> = check.model.iter().map(|t| t.id.as_str()).collect();
    assert!(!check.new_templates.is_empty());
    assert!(check.new_templates.iter().all(|t| !known.contains(t.id.as_str())));
    assert!(output.templates.iter().all(|t| known.contains(t.id.as_str())));
}

#[test]
fn a_state_that_evicts_is_refused() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, "good.log", &known_lines(0..100));
    let state = saved(&log);

    let error = check_records(&request(&log, Some(state), false, OnFull::Evict), &NullObserver).unwrap_err();

    assert!(matches!(error, EngineError::Config(message) if message.contains("on_full")));
}

#[test]
fn checking_needs_a_state() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, "good.log", &known_lines(0..100));

    let error = check_records(&request(&log, None, false, OnFull::Pool), &NullObserver).unwrap_err();

    assert!(matches!(error, EngineError::Config(message) if message.contains("saved state")));
}
