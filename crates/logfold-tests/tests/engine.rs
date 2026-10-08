#![allow(missing_docs)]

use std::io::Write;
use std::path::PathBuf;

use logfold_core::default_mask_rules;
use logfold_engine::{MineRequest, MiningParams, NoObserver, Strategy, mine};
use logfold_io::{FormatConfig, FormatSpec};

fn write_log(dir: &tempfile::TempDir, name: &str, lines: usize, seed: usize) -> PathBuf {
    let path = dir.path().join(name);
    let mut file = std::fs::File::create(&path).unwrap();
    for i in 0..lines {
        let n = i + seed;
        match n % 5 {
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
            _ => writeln!(file, "2026-10-04T12:00:{:02}Z DEBUG heartbeat", n % 60),
        }
        .unwrap();
    }
    path
}

fn request(runs: Vec<Vec<PathBuf>>, strategy: Strategy) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs,
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

fn summary(output: &logfold_engine::MineOutput) -> Vec<(String, Vec<u64>)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs.iter().map(|r| r.count).collect())).collect()
}

#[test]
fn sequential_counts_every_record() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, "a.log", 5000, 0);
    let output = mine(&request(vec![vec![path]], Strategy::Sequential), &NoObserver).unwrap();
    assert_eq!(output.runs[0].records, 5000);
    assert_eq!(output.runs[0].lines, 5000);
    let total: u64 = output.templates.iter().map(|t| t.total()).sum();
    assert_eq!(total, 5000);
    assert!(output.templates.len() < 40, "unexpected template explosion: {}", output.templates.len());
}

#[test]
fn chunked_is_deterministic_across_thread_counts() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, "a.log", 20_000, 0);
    let run = |threads| {
        let strategy = Strategy::Chunked { chunk_bytes: 64 * 1024, threads };
        mine(&request(vec![vec![path.clone()]], strategy), &NoObserver).unwrap()
    };
    let one = run(1);
    assert!(one.metrics.chunks > 4);
    let baseline = summary(&one);
    for threads in [2, 3, 8] {
        assert_eq!(summary(&run(threads)), baseline, "threads = {threads}");
    }
    let total: u64 = one.templates.iter().map(|t| t.total()).sum();
    assert_eq!(total, 20_000);
    assert_eq!(one.runs[0].records, 20_000);
}

#[test]
fn chunked_matches_sequential_on_simple_logs() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_log(&dir, "a.log", 20_000, 0);
    let sequential = mine(&request(vec![vec![path.clone()]], Strategy::Sequential), &NoObserver).unwrap();
    let chunked =
        mine(&request(vec![vec![path]], Strategy::Chunked { chunk_bytes: 100 * 1024, threads: 4 }), &NoObserver)
            .unwrap();
    assert_eq!(summary(&sequential), summary(&chunked));
}

#[test]
fn two_runs_keep_separate_counters() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 1000, 0);
    let after = write_log(&dir, "after.log", 3000, 7);
    let output = mine(&request(vec![vec![before], vec![after]], Strategy::Sequential), &NoObserver).unwrap();
    assert_eq!(output.runs[0].records, 1000);
    assert_eq!(output.runs[1].records, 3000);
    let per_run: Vec<u64> = (0..2).map(|r| output.templates.iter().map(|t| t.runs[r].count).sum()).collect();
    assert_eq!(per_run, vec![1000, 3000]);
}

#[test]
fn missing_file_is_an_io_error() {
    let result = mine(&request(vec![vec![PathBuf::from("does-not-exist.log")]], Strategy::Sequential), &NoObserver);
    assert!(matches!(result, Err(logfold_engine::EngineError::Io(_))));
}

fn recount_request(runs: Vec<Vec<PathBuf>>, strategy: Strategy, mining: MiningParams) -> MineRequest {
    MineRequest { mining, recount: true, ..request(runs, strategy) }
}

#[test]
fn recount_makes_identical_runs_identical() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("tricky.log");
    std::fs::write(&path, "a\n<*>\na\n<*>\na\n").unwrap();
    let mining = MiningParams { depth: 3, sim_th: 0.3, max_children: 1, max_templates: 2, ..MiningParams::default() };
    let recounted =
        mine(&recount_request(vec![vec![path.clone()], vec![path]], Strategy::Sequential, mining), &NoObserver)
            .unwrap();
    for template in &recounted.templates {
        assert_eq!(template.runs[0].count, template.runs[1].count, "{}", template.text);
    }
    let total: u64 = recounted.templates.iter().map(|t| t.total()).sum();
    assert_eq!(total, 10);
}

#[test]
fn recount_is_deterministic_across_threads_and_conserves_records() {
    let dir = tempfile::tempdir().unwrap();
    let before = write_log(&dir, "before.log", 12_000, 0);
    let after = write_log(&dir, "after.log", 12_000, 0);
    let run = |threads| {
        let strategy = Strategy::Chunked { chunk_bytes: 64 * 1024, threads };
        mine(
            &recount_request(vec![vec![before.clone()], vec![after.clone()]], strategy, MiningParams::default()),
            &NoObserver,
        )
        .unwrap()
    };
    let one = run(1);
    let baseline = summary(&one);
    for threads in [2, 5] {
        assert_eq!(summary(&run(threads)), baseline, "threads = {threads}");
    }
    for template in &one.templates {
        assert_eq!(template.runs[0].count, template.runs[1].count, "{}", template.text);
    }
    let per_run: Vec<u64> = (0..2).map(|r| one.templates.iter().map(|t| t.runs[r].count).sum()).collect();
    assert_eq!(per_run, vec![12_000, 12_000]);
    assert!(one.metrics.wall_recount_s > 0.0);
}
