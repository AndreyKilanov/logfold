#![allow(missing_docs)]

use std::io::Write;
use std::path::{Path, PathBuf};

use logfold_core::default_mask_rules;
use logfold_engine::{ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, mine};
use logfold_io::{FormatConfig, FormatSpec};

const MIB: u64 = 1024 * 1024;

fn letters(mut n: usize) -> String {
    let mut word = String::new();
    for _ in 0..6 {
        word.push((b'a' + (n % 26) as u8) as char);
        n /= 26;
    }
    word
}

/// A few message shapes with words that vary, so that chunk trees differ in their generalizations.
fn write_log(dir: &tempfile::TempDir, lines: usize) -> PathBuf {
    let path = dir.path().join("mixed.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for i in 0..lines {
        let word = |k: usize| letters((i * 7 + k * 13) % 331);
        match i % 7 {
            0 | 1 => writeln!(file, "INFO dfs.DataNode: Receiving block {} src {} dest {}", word(1), word(2), word(3)),
            2 | 3 => writeln!(
                file,
                "INFO dfs.DataNode: Served block {} src {} dest {} size {}",
                word(1),
                word(2),
                word(3),
                word(4)
            ),
            4 => writeln!(
                file,
                "INFO dfs.DataNode: {} {} {} block {} {} {}",
                word(1),
                word(2),
                word(3),
                word(4),
                word(5),
                word(6)
            ),
            5 => writeln!(file, "WARN dfs.DataNode: Deleting block {} file {}", word(1), word(2)),
            _ => writeln!(file, "ERROR dfs.DataNode: write failed block {}", word(1)),
        }
        .unwrap();
    }
    path
}

fn request(path: &Path, strategy: ExecutionStrategy, warm_start: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy,
        warm_start,
        recount: false,
        initial: None,
        keep_snapshot: false,
    }
}

fn summary(output: &MineOutput) -> Vec<(String, Vec<u64>)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs.iter().map(|r| r.count).collect())).collect()
}

#[test]
fn a_warm_start_is_deterministic_across_thread_counts() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, 60_000);
    let run = |threads| {
        mine(&request(&path, ExecutionStrategy::Chunked { chunk_bytes: 128 * 1024, threads }, true), &NullObserver)
            .unwrap()
    };
    let baseline = run(1);
    assert!(baseline.metrics.chunks > 4);
    assert_eq!(baseline.metrics.strategy, "chunked");
    for threads in [2, 3, 8] {
        assert_eq!(summary(&run(threads)), summary(&baseline), "threads = {threads}");
    }
}

#[test]
fn a_warm_start_counts_every_record_once() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, 60_000);
    let output =
        mine(&request(&path, ExecutionStrategy::Chunked { chunk_bytes: 128 * 1024, threads: 4 }, true), &NullObserver)
            .unwrap();
    assert_eq!(output.runs[0].records, 60_000);
    let total: u64 = output.templates.iter().map(|t| t.total()).sum();
    assert_eq!(total, 60_000);
}

#[test]
fn a_warm_start_changes_nothing_for_one_chunk() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, 5000);
    let strategy = ExecutionStrategy::Chunked { chunk_bytes: 64 * MIB, threads: 4 };
    let cold = mine(&request(&path, strategy, false), &NullObserver).unwrap();
    let warm = mine(&request(&path, strategy, true), &NullObserver).unwrap();
    assert_eq!(summary(&cold), summary(&warm));
}

/// Frequent message shapes plus a thin stream of rare ones, drawn from word pools: a chunk that starts cold generalizes
/// the rare ones into stray templates that differ from chunk to chunk.
fn write_stray(dir: &tempfile::TempDir, lines: usize) -> PathBuf {
    let path = dir.path().join("stray.log");
    let mut file = std::fs::File::create(&path).unwrap();
    let mut state = 0x9E37_79B9_7F4A_7C15u64;
    let mut next = move |bound: u64| {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state % bound
    };
    let verbs = ["Receiving", "Received", "Deleting"];
    for _ in 0..lines {
        let rare = next(1000) < 2;
        let verb = verbs[next(3) as usize];
        let with_size = next(2) == 0;
        let w: Vec<String> = (0..6).map(|_| letters(next(400) as usize)).collect();
        if rare {
            writeln!(file, "INFO dfs.DataNode: {} {} {} block {} {} {}", w[0], w[1], w[2], w[3], w[4], w[5])
        } else if with_size {
            writeln!(file, "INFO dfs.DataNode: {verb} block {} src {} dest {} size {}", w[0], w[1], w[2], w[3])
        } else {
            writeln!(file, "INFO dfs.DataNode: {verb} block {} src {} dest {}", w[0], w[1], w[2])
        }
        .unwrap();
    }
    path
}

#[test]
fn a_warm_start_gives_fewer_stray_templates_than_a_cold_one() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_stray(&dir, 300_000);
    let strategy = ExecutionStrategy::Chunked { chunk_bytes: MIB, threads: 4 };
    let cold = mine(&request(&path, strategy, false), &NullObserver).unwrap();
    let warm = mine(&request(&path, strategy, true), &NullObserver).unwrap();
    eprintln!("cold {} warm {}", cold.templates.len(), warm.templates.len());
    assert!(warm.templates.len() < cold.templates.len(), "{} against {}", warm.templates.len(), cold.templates.len());
}

#[test]
fn an_adaptive_run_with_a_warm_start_still_gives_up_on_unique_messages() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("unique.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for i in 0..60_000 {
        let words: Vec<String> = (0..5).map(|k| letters(i * (2 * k + 3) + k)).collect();
        writeln!(file, "INFO {}", words.join(" ")).unwrap();
    }
    drop(file);
    let strategy = ExecutionStrategy::Adaptive { chunk_bytes: MIB, threads: 4 };
    let adaptive = mine(&request(&path, strategy, true), &NullObserver).unwrap();
    let sequential = mine(&request(&path, ExecutionStrategy::Sequential, false), &NullObserver).unwrap();
    assert_eq!(adaptive.metrics.strategy, "sequential");
    assert_eq!(summary(&adaptive), summary(&sequential));
}

#[test]
fn an_adaptive_run_with_a_warm_start_keeps_repetitive_logs_chunked() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, 80_000);
    let strategy = ExecutionStrategy::Adaptive { chunk_bytes: 256 * 1024, threads: 4 };
    let adaptive = mine(&request(&path, strategy, true), &NullObserver).unwrap();
    let chunked =
        mine(&request(&path, ExecutionStrategy::Chunked { chunk_bytes: 256 * 1024, threads: 4 }, true), &NullObserver)
            .unwrap();
    assert_eq!(adaptive.metrics.strategy, "chunked");
    assert_eq!(summary(&adaptive), summary(&chunked));
}
