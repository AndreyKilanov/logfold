#![allow(missing_docs)]
//! A session over any records: the way the records are cut into batches never changes the templates or the counts, and
//! the result is the one of mining the same records from a file.

mod common;

use std::path::PathBuf;

use common::lines;
use logfold_core::default_mask_rules;
use logfold_engine::{
    ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, Session, SessionConfig, mine,
};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

fn plain() -> FormatConfig {
    FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false }
}

fn write_log(dir: &tempfile::TempDir, stream: &[String]) -> PathBuf {
    let path = dir.path().join("a.log");
    std::fs::write(&path, stream.join("\n") + "\n").unwrap();
    path
}

fn from_file(path: PathBuf) -> MineOutput {
    let request = MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path]],
        format: plain(),
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy: ExecutionStrategy::Sequential,
        warm_start: false,
        recount: false,
        initial: None,
        keep_snapshot: false,
    };
    mine(&request, &NullObserver).unwrap()
}

fn session() -> Session {
    Session::new(SessionConfig {
        format: plain(),
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        initial: None,
    })
    .unwrap()
}

fn answer(output: &MineOutput) -> (Vec<(String, u64)>, u64, u64) {
    let templates = output.templates.iter().map(|t| (t.text.clone(), t.runs[0].count)).collect();
    (templates, output.runs[0].records, output.runs[0].lines)
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
        stream in lines(250),
        sizes in prop::collection::vec(1usize..40, 1..6),
    ) {
        let dir = tempfile::tempdir().unwrap();
        let expected = answer(&from_file(write_log(&dir, &stream)));

        let mut by_lines = session();
        for part in cut(&stream, &sizes) {
            by_lines.add_lines(part.iter().map(|line| line.as_bytes()));
        }
        by_lines.flush();
        prop_assert_eq!(answer(&by_lines.output()), expected.clone());

        let mut by_records = session();
        for part in cut(&stream, &sizes) {
            by_records.add_records(part.iter().map(|line| line.as_bytes()));
        }
        prop_assert_eq!(answer(&by_records.output()), expected);
    }

    #[test]
    fn the_templates_reported_as_new_are_the_templates_created(stream in lines(200)) {
        let mut live = session();
        let mut reported = 0usize;
        for line in &stream {
            live.add_lines([line.as_bytes()]);
            reported += live.take_new_templates().len();
        }
        let created = live.snapshot().clusters.len();
        prop_assert_eq!(reported, created);
    }
}
