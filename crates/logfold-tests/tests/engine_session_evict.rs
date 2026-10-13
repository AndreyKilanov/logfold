#![allow(missing_docs)]

//! Mining that evicts: a live session gives the result of mining the same records from a file whatever the batches are,
//! the chunked strategy is refused, and the adaptive one mines with one tree.

mod common;

use std::path::PathBuf;

use common::lines;
use logfold_core::{OnFull, default_mask_rules};
use logfold_engine::{
    EngineError, ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, Session, SessionConfig, mine,
};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

fn plain() -> FormatConfig {
    FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false }
}

fn evicting(max_templates: usize) -> MiningConfig {
    MiningConfig { max_templates, on_full: OnFull::Evict, ..MiningConfig::default() }
}

fn write_log(dir: &tempfile::TempDir, stream: &[String]) -> PathBuf {
    let path = dir.path().join("a.log");
    std::fs::write(&path, stream.join("\n") + "\n").unwrap();
    path
}

fn request(path: PathBuf, mining: MiningConfig, strategy: ExecutionStrategy) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path]],
        format: plain(),
        masks: default_mask_rules(),
        mining,
        strategy,
        warm_start: false,
        recount: false,
        initial: None,
        keep_snapshot: false,
    }
}

fn answer(output: &MineOutput) -> (Vec<(String, u64)>, u64, u64, bool) {
    let templates = output.templates.iter().map(|t| (t.text.clone(), t.runs[0].count)).collect();
    (templates, output.runs[0].records, output.runs[0].evicted, output.runs[0].overflowed)
}

fn stream(count: usize) -> Vec<String> {
    (0..count).map(|n| format!("shape{n}a shape{n}b shape{n}c")).collect()
}

#[test]
fn the_runs_report_how_many_templates_were_evicted_and_the_totals_add_up() {
    let dir = tempfile::tempdir().unwrap();
    let records = stream(300);
    let path = write_log(&dir, &records);
    let output = mine(&request(path, evicting(50), ExecutionStrategy::Sequential), &NullObserver).unwrap();
    let run = &output.runs[0];
    assert_eq!(run.records, 300);
    assert!(run.evicted >= 250 - 50, "evicted {}", run.evicted);
    assert!(run.overflowed);
    assert!(output.templates.len() <= 51);
    let counted: u64 = output.templates.iter().map(|t| t.runs[0].count).sum();
    assert_eq!(counted, 300);
}

#[test]
fn the_default_policy_evicts_nothing() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, &stream(300));
    let mining = MiningConfig { max_templates: 50, ..MiningConfig::default() };
    let output = mine(&request(path, mining, ExecutionStrategy::Sequential), &NullObserver).unwrap();
    assert_eq!(output.runs[0].evicted, 0);
    assert!(output.templates.iter().any(|t| t.text == "shape0a shape0b shape0c"));
}

#[test]
fn the_chunked_strategy_is_refused_and_the_adaptive_one_mines_with_one_tree() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, &stream(400));
    let chunked = ExecutionStrategy::Chunked { chunk_bytes: 2048, threads: 4 };
    match mine(&request(path.clone(), evicting(50), chunked), &NullObserver) {
        Err(EngineError::Config(message)) => assert!(message.contains("sequential"), "{message}"),
        other => panic!("expected a refusal, got {other:?}"),
    }
    let adaptive = ExecutionStrategy::Adaptive { chunk_bytes: 2048, threads: 4 };
    let one = mine(&request(path.clone(), evicting(50), adaptive), &NullObserver).unwrap();
    let sequential = mine(&request(path, evicting(50), ExecutionStrategy::Sequential), &NullObserver).unwrap();
    assert_eq!(answer(&one), answer(&sequential));
    assert_eq!(one.metrics.strategy, "sequential");
}

fn session(max_templates: usize) -> Session {
    Session::new(SessionConfig {
        format: plain(),
        masks: default_mask_rules(),
        mining: evicting(max_templates),
        initial: None,
    })
    .unwrap()
}

fn cut<'a>(stream: &'a [String], sizes: &[usize]) -> Vec<&'a [String]> {
    let mut parts = Vec::new();
    let mut rest = stream;
    for size in sizes.iter().cycle() {
        if rest.is_empty() {
            break;
        }
        let (head, tail) = rest.split_at((*size).min(rest.len()));
        parts.push(head);
        rest = tail;
    }
    parts
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(48))]

    #[test]
    fn any_cut_into_batches_gives_the_result_of_mining_the_file(
        records in lines(250),
        limit in 1usize..30,
        sizes in prop::collection::vec(1usize..40, 1..6),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let expected =
            answer(&mine(&request(write_log(&dir, &records), evicting(limit), ExecutionStrategy::Sequential), &NullObserver).unwrap());
        let mut live = session(limit);
        for part in cut(&records, &sizes) {
            live.add_records(part.iter().map(|line| line.as_bytes()));
        }
        prop_assert_eq!(answer(&live.output()), expected);
    }
}
