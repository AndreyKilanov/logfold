#![allow(missing_docs)]

//! Continuing a saved miner: sequentially, and in parallel from the loaded tree as the seed of every chunk.

use std::io::Write;
use std::path::{Path, PathBuf};

use logfold_core::{DrainMiner, MinerSnapshot, default_mask_rules};
use logfold_engine::{ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, mine, threads_for_seed};
use logfold_io::{FormatConfig, FormatSpec};

fn write_log(dir: &tempfile::TempDir, name: &str, range: std::ops::Range<usize>) -> PathBuf {
    let path = dir.path().join(name);
    let mut file = std::fs::File::create(&path).unwrap();
    for n in range {
        match n % 7 {
            0 => writeln!(
                file,
                "2026-10-04T12:00:{:02}Z INFO user u{} logged in from 10.0.{}.{}",
                n % 60,
                n % 97,
                n % 8,
                n % 250
            ),
            1 => {
                writeln!(file, "2026-10-04T12:00:{:02}Z WARN disk usage {}% on /dev/sda{}", n % 60, 50 + n % 40, n % 3)
            }
            2 => {
                writeln!(file, "2026-10-04T12:00:{:02}Z ERROR request {} failed with status {}", n % 60, n, 500 + n % 4)
            }
            3 => writeln!(file, "2026-10-04T12:00:{:02}Z INFO cache miss for key k{}", n % 60, n % 1013),
            4 => writeln!(
                file,
                "2026-10-04T12:00:{:02}Z DEBUG worker w{} took {}ms for tenant t{}",
                n % 60,
                n % 9,
                n % 700,
                n % 4
            ),
            5 => writeln!(file, "2026-10-04T12:00:{:02}Z INFO job {} finished", n % 60, n),
            _ => writeln!(file, "2026-10-04T12:00:{:02}Z DEBUG heartbeat", n % 60),
        }
        .unwrap();
    }
    path
}

fn request(
    path: &Path,
    strategy: ExecutionStrategy,
    initial: Option<MinerSnapshot>,
    keep_snapshot: bool,
) -> MineRequest {
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
        keep_snapshot,
    }
}

fn chunked(threads: usize) -> ExecutionStrategy {
    ExecutionStrategy::Chunked { chunk_bytes: 16 * 1024, threads }
}

fn saved(first: &Path) -> MinerSnapshot {
    mine(&request(first, ExecutionStrategy::Sequential, None, true), &NullObserver).unwrap().snapshot.unwrap()
}

fn records(output: &MineOutput) -> u64 {
    output.templates.iter().map(|t| t.runs[0].count).sum()
}

fn texts(output: &MineOutput) -> Vec<(String, u64)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs[0].count)).collect()
}

#[test]
fn a_loaded_tree_seeds_every_chunk_and_every_record_is_counted() {
    let dir = tempfile::tempdir().unwrap();
    let first = write_log(&dir, "a.log", 0..4000);
    let second = write_log(&dir, "b.log", 4000..24000);
    let state = saved(&first);
    let output = mine(&request(&second, chunked(4), Some(state), false), &NullObserver).unwrap();
    assert_eq!(output.metrics.strategy, "chunked");
    assert!(output.metrics.chunks > 4, "the log must be cut into many chunks ({})", output.metrics.chunks);
    assert_eq!(output.runs[0].records, 20000);
    assert_eq!(records(&output), 20000, "the report counts the new run only");
}

#[test]
fn the_parallel_resume_does_not_depend_on_the_number_of_threads() {
    let dir = tempfile::tempdir().unwrap();
    let first = write_log(&dir, "a.log", 0..4000);
    let second = write_log(&dir, "b.log", 4000..24000);
    let state = saved(&first);
    let one = mine(&request(&second, chunked(1), Some(state.clone()), true), &NullObserver).unwrap();
    for threads in [2, 5, 16] {
        let many = mine(&request(&second, chunked(threads), Some(state.clone()), true), &NullObserver).unwrap();
        assert_eq!(texts(&many), texts(&one), "{threads} threads");
        assert_eq!(many.snapshot, one.snapshot, "{threads} threads: the saved state too");
    }
}

#[test]
fn the_parallel_resume_finds_the_templates_of_the_sequential_one() {
    let dir = tempfile::tempdir().unwrap();
    let first = write_log(&dir, "a.log", 0..4000);
    let second = write_log(&dir, "b.log", 4000..24000);
    let state = saved(&first);
    let sequential =
        mine(&request(&second, ExecutionStrategy::Sequential, Some(state.clone()), false), &NullObserver).unwrap();
    let parallel = mine(&request(&second, chunked(4), Some(state), false), &NullObserver).unwrap();
    assert_eq!(records(&sequential), records(&parallel));
    let wanted = texts(&sequential);
    let found = texts(&parallel);
    let shared: u64 =
        wanted.iter().filter(|(text, _)| found.iter().any(|(other, _)| other == text)).map(|(_, count)| count).sum();
    assert!(
        shared * 100 >= records(&sequential) * 98,
        "{shared} of {} records are in templates of both",
        records(&sequential)
    );
}

#[test]
fn the_state_saved_after_a_parallel_resume_loads_and_keeps_the_history() {
    let dir = tempfile::tempdir().unwrap();
    let first = write_log(&dir, "a.log", 0..4000);
    let second = write_log(&dir, "b.log", 4000..24000);
    let after =
        mine(&request(&second, chunked(4), Some(saved(&first)), true), &NullObserver).unwrap().snapshot.unwrap();
    let all: u64 = after.clusters.iter().map(|c| c.history.count).sum::<u64>()
        + after.overflow.iter().map(|(_, c)| c.history.count).sum::<u64>();
    assert_eq!(all, 24000, "the history holds the records of both runs");
    assert!(DrainMiner::from_snapshot(after, 1).is_ok());
}

#[test]
fn a_loaded_state_with_one_chunk_is_continued_sequentially() {
    let dir = tempfile::tempdir().unwrap();
    let first = write_log(&dir, "a.log", 0..4000);
    let second = write_log(&dir, "b.log", 4000..4100);
    let state = saved(&first);
    let one_chunk = ExecutionStrategy::Chunked { chunk_bytes: 64 << 20, threads: 4 };
    let output = mine(&request(&second, one_chunk, Some(state.clone()), true), &NullObserver).unwrap();
    let sequential = mine(&request(&second, ExecutionStrategy::Sequential, Some(state), true), &NullObserver).unwrap();
    assert_eq!(output.snapshot, sequential.snapshot, "one chunk is the same as one tree");
    assert_eq!(output.metrics.strategy, "sequential");
}

#[test]
fn adaptive_with_a_loaded_state_goes_parallel_without_judging_the_first_chunk() {
    let dir = tempfile::tempdir().unwrap();
    let first = write_log(&dir, "a.log", 0..4000);
    let second = write_log(&dir, "b.log", 4000..24000);
    let adaptive = ExecutionStrategy::Adaptive { chunk_bytes: 16 * 1024, threads: 4 };
    let output = mine(&request(&second, adaptive, Some(saved(&first)), false), &NullObserver).unwrap();
    assert_eq!(output.metrics.strategy, "chunked");
    assert_eq!(records(&output), 20000);
}

#[test]
fn a_large_loaded_tree_gets_fewer_threads_so_that_its_copies_fit_the_memory() {
    assert_eq!(threads_for_seed(1_000, 16), 16, "a small tree keeps every thread");
    assert_eq!(threads_for_seed(100_000, 16), 16);
    assert_eq!(threads_for_seed(1_000_000, 16), 3, "a state of the default limit gets a few");
    assert_eq!(threads_for_seed(10_000_000, 16), 1, "a huge tree is continued by one thread");
    assert_eq!(threads_for_seed(1_000, 0), 1, "never fewer than one");
    assert_eq!(threads_for_seed(usize::MAX, 4), 1, "no overflow");
}
