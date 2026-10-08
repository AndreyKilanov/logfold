#![allow(missing_docs)]
//! The engine counts every record and, for a fixed chunk size, does not depend on the number of threads.

mod common;

use std::path::PathBuf;

use common::lines;
use logfold_core::default_mask_rules;
use logfold_engine::{MineOutput, MineRequest, MiningParams, NoObserver, Strategy, mine};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

fn write_log(dir: &tempfile::TempDir, stream: &[String]) -> PathBuf {
    let path = dir.path().join("generated.log");
    std::fs::write(&path, stream.join("\n") + "\n").unwrap();
    path
}

fn request(path: PathBuf, strategy: Strategy) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path]],
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningParams::default(),
        strategy,
        warm_start: false,
        recount: false,
        initial: None,
        keep_snapshot: false,
    }
}

fn summary(output: &MineOutput) -> Vec<(String, Vec<u64>)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs.iter().map(|r| r.count).collect())).collect()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(24))]

    #[test]
    fn every_record_is_counted_by_every_strategy(stream in lines(400), chunk_bytes in 64u64..2048) {
        let dir = tempfile::tempdir().unwrap();
        let path = write_log(&dir, &stream);
        let strategies = [Strategy::Sequential, Strategy::Chunked { chunk_bytes, threads: 2 }];
        for strategy in strategies {
            let output = mine(&request(path.clone(), strategy), &NoObserver).unwrap();
            prop_assert_eq!(output.runs[0].records, stream.len() as u64);
            let counted: u64 = output.templates.iter().map(|template| template.total()).sum();
            prop_assert_eq!(counted, stream.len() as u64);
        }
    }

    #[test]
    fn the_chunked_result_does_not_depend_on_the_thread_count(
        stream in lines(400),
        chunk_bytes in 64u64..2048,
        threads in 2usize..=4,
    ) {
        let dir = tempfile::tempdir().unwrap();
        let path = write_log(&dir, &stream);
        let run = |threads| {
            let output = mine(&request(path.clone(), Strategy::Chunked { chunk_bytes, threads }), &NoObserver);
            summary(&output.unwrap())
        };
        prop_assert_eq!(run(1), run(threads));
    }
}
