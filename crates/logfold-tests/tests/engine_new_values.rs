#![allow(missing_docs)]

//! The values that are new and gone between two runs: the same for any number of threads at a fixed chunk size, the
//! text of the values from a second pass, and no change for a template that only one run has.

use std::io::Write;
use std::path::{Path, PathBuf};

use logfold_core::default_mask_rules;
use logfold_engine::{
    ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, TemplateChanges, ValuesRequest, mine,
};
use logfold_io::{FormatConfig, FormatSpec};

fn write_log(dir: &tempfile::TempDir, name: &str, ids: std::ops::RangeInclusive<u32>, extra: &str) -> PathBuf {
    let path = dir.path().join(name);
    let mut file = std::fs::File::create(&path).unwrap();
    for id in ids {
        for _ in 0..(id % 3 + 1) {
            writeln!(file, "added item {id} to the catalog").unwrap();
        }
        writeln!(file, "health check ok").unwrap();
    }
    if !extra.is_empty() {
        writeln!(file, "{extra}").unwrap();
    }
    path
}

fn request(runs: &[&Path], strategy: ExecutionStrategy, compare: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: runs.iter().map(|path| vec![path.to_path_buf()]).collect(),
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy,
        warm_start: false,
        recount: true,
        initial: None,
        keep_snapshot: false,
        values: Some(ValuesRequest { templates: 10, compare }),
    }
}

fn changes_of<'a>(output: &'a MineOutput, prefix: &str) -> Option<&'a TemplateChanges> {
    output.value_changes.as_ref().unwrap().iter().find(|template| template.text.starts_with(prefix))
}

fn texts(values: &[(Vec<u8>, u64)]) -> Vec<String> {
    values.iter().map(|(value, _)| String::from_utf8(value.clone()).unwrap()).collect()
}

#[test]
fn the_new_and_the_gone_ids_are_listed_with_their_text_and_counts() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 1..=50, "");
    let after = write_log(&dir, "after.log", 31..=80, "");
    let output = mine(&request(&[&before, &after], ExecutionStrategy::Sequential, true), &NullObserver).unwrap();

    assert!(output.values.is_none());
    let item = changes_of(&output, "added item").unwrap();
    assert_eq!(item.text, "added item <NUM> to the catalog");
    assert_eq!(item.positions.len(), 1);
    let change = &item.positions[0];
    assert_eq!((change.position, change.name.as_str()), (2, "num"));
    assert_eq!((change.new_distinct, change.gone_distinct, change.shared_distinct), (30, 30, 20));
    assert_eq!(change.distinct, (50, 50));
    assert!(!change.capped);

    assert_eq!(change.new.len(), 10);
    assert_eq!(change.gone.len(), 10);
    assert!(change.new.iter().all(|(_, count)| *count == 3), "the most frequent come first: {:?}", change.new);
    assert_eq!(texts(&change.new), ["53", "56", "59", "62", "65", "68", "71", "74", "77", "80"]);
    assert_eq!(texts(&change.gone), ["11", "14", "17", "2", "20", "23", "26", "29", "5", "8"]);
    assert!(changes_of(&output, "health check").is_none());
}

#[test]
fn a_template_that_only_one_run_has_is_not_compared() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 1..=10, "");
    let after = write_log(&dir, "after.log", 1..=10, "cache warmed in 12 ms");
    let output = mine(&request(&[&before, &after], ExecutionStrategy::Sequential, true), &NullObserver).unwrap();
    assert!(output.value_changes.unwrap().is_empty());
}

#[test]
fn the_same_ids_in_both_runs_are_no_change() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 1..=10, "");
    let after = write_log(&dir, "after.log", 1..=10, "");
    let output = mine(&request(&[&before, &after], ExecutionStrategy::Sequential, true), &NullObserver).unwrap();
    assert!(output.value_changes.unwrap().is_empty());
}

#[test]
fn the_result_does_not_depend_on_the_threads() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 1..=4000, "");
    let after = write_log(&dir, "after.log", 2001..=6000, "");
    let run = |strategy| {
        let output = mine(&request(&[&before, &after], strategy, true), &NullObserver).unwrap();
        changes_of(&output, "added item").unwrap().clone()
    };
    let sequential = run(ExecutionStrategy::Sequential);
    assert_eq!(sequential.positions[0].new_distinct, 2000);
    assert_eq!(sequential.positions[0].gone_distinct, 2000);
    for threads in [1, 3, 8] {
        let chunked = run(ExecutionStrategy::Chunked { chunk_bytes: 40_000, threads });
        assert_eq!(chunked.positions, sequential.positions, "threads = {threads}");
    }
}

#[test]
fn comparing_needs_two_runs() {
    let dir = tempfile::tempdir().unwrap();
    let only = write_log(&dir, "only.log", 1..=5, "");
    let error = mine(&request(&[&only], ExecutionStrategy::Sequential, true), &NullObserver).unwrap_err();
    assert!(error.to_string().contains("two runs"), "{error}");
}

#[test]
fn without_the_comparison_the_distributions_are_still_returned() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 1..=5, "");
    let after = write_log(&dir, "after.log", 3..=8, "");
    let output = mine(&request(&[&before, &after], ExecutionStrategy::Sequential, false), &NullObserver).unwrap();
    assert!(output.value_changes.is_none());
    assert!(output.values.is_some());
}
