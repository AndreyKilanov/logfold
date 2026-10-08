#![allow(missing_docs)]
//! Matching a log against a saved miner: every record is matched or unmatched, the state is not changed, and the answer
//! does not depend on the strategy or the number of threads.

mod common;

use std::path::PathBuf;

use common::lines;
use logfold_core::{MinerSnapshot, default_mask_rules};
use logfold_engine::{ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, match_records, mine};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

fn write_log(dir: &tempfile::TempDir, name: &str, stream: &[String]) -> PathBuf {
    let path = dir.path().join(name);
    std::fs::write(&path, stream.join("\n") + "\n").unwrap();
    path
}

fn request(path: PathBuf, strategy: ExecutionStrategy, initial: Option<MinerSnapshot>, keep: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path]],
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

type Answer = (Vec<(String, u64)>, Option<Vec<Vec<(usize, u64)>>>, u64);

fn answer(output: &MineOutput) -> Answer {
    let templates = output.templates.iter().map(|t| (t.text.clone(), t.runs[0].count)).collect();
    (templates, output.unmatched.clone(), output.runs[0].records)
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(24))]

    #[test]
    fn matched_and_unmatched_records_add_up_and_the_state_stays_as_it_was(
        trained in lines(300),
        fresh in lines(300),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let first = write_log(&dir, "first.log", &trained);
        let second = write_log(&dir, "second.log", &fresh);
        let state = mine(&request(first, ExecutionStrategy::Sequential, None, true), &NullObserver)
            .unwrap()
            .snapshot
            .unwrap();
        let before = state.clone();
        let output = match_records(
            &request(second, ExecutionStrategy::Sequential, Some(state.clone()), false),
            &NullObserver,
        )
        .unwrap();
        let matched: u64 = output.templates.iter().map(|template| template.total()).sum();
        let unmatched: u64 = output.unmatched.as_ref().unwrap()[0].iter().map(|(_, records)| records).sum();
        prop_assert_eq!(matched + unmatched, fresh.len() as u64);
        prop_assert_eq!(output.runs[0].records, fresh.len() as u64);
        prop_assert!(output.snapshot.is_none());
        prop_assert_eq!(state, before);
    }

    #[test]
    fn the_answer_does_not_depend_on_the_strategy_or_the_threads(
        trained in lines(200),
        fresh in lines(400),
        chunk_bytes in 64u64..2048,
        threads in 1usize..=4,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let first = write_log(&dir, "first.log", &trained);
        let second = write_log(&dir, "second.log", &fresh);
        let state = mine(&request(first, ExecutionStrategy::Sequential, None, true), &NullObserver)
            .unwrap()
            .snapshot
            .unwrap();
        let run = |strategy| {
            let output = match_records(&request(second.clone(), strategy, Some(state.clone()), false), &NullObserver);
            answer(&output.unwrap())
        };
        prop_assert_eq!(run(ExecutionStrategy::Sequential), run(ExecutionStrategy::Chunked { chunk_bytes, threads }));
    }
}
