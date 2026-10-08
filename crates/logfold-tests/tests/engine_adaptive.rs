#![allow(missing_docs)]

use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

use logfold_core::default_mask_rules;
use logfold_engine::{EngineError, MineOutput, MineRequest, MiningParams, NoObserver, Observer, Strategy, mine};
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

/// Every record is a template of its own: five words that no other record has (too few shared tokens to merge).
fn write_unique(dir: &tempfile::TempDir, lines: usize) -> PathBuf {
    let path = dir.path().join("unique.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for i in 0..lines {
        let words: Vec<String> = (0..5).map(|k| letters(i * (2 * k + 3) + k)).collect();
        writeln!(file, "2026-10-04T12:00:00Z INFO {}", words.join(" ")).unwrap();
    }
    path
}

/// Five message shapes repeated over and over.
fn write_repetitive(dir: &tempfile::TempDir, lines: usize) -> PathBuf {
    let path = dir.path().join("repetitive.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for i in 0..lines {
        match i % 5 {
            0 => writeln!(file, "2026-10-04T12:00:00Z INFO user u{} logged in from 10.0.0.{}", i % 97, i % 250),
            1 => writeln!(file, "2026-10-04T12:00:00Z WARN disk usage {}% on /dev/sda{}", 50 + i % 40, i % 3),
            2 => writeln!(file, "2026-10-04T12:00:00Z ERROR request {} failed with status {}", i, 500 + i % 4),
            3 => writeln!(file, "2026-10-04T12:00:00Z INFO cache miss for key k{}", i % 1013),
            _ => writeln!(file, "2026-10-04T12:00:00Z DEBUG heartbeat"),
        }
        .unwrap();
    }
    path
}

fn request(path: &Path, strategy: Strategy, recount: bool) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningParams::default(),
        strategy,
        warm_start: false,
        recount,
        initial: None,
        keep_snapshot: false,
    }
}

fn summary(output: &MineOutput) -> Vec<(String, Vec<u64>)> {
    output.templates.iter().map(|t| (t.text.clone(), t.runs.iter().map(|r| r.count).collect())).collect()
}

struct Bytes(AtomicU64);

impl Observer for Bytes {
    fn on_bytes(&self, consumed: u64) {
        self.0.fetch_add(consumed, Ordering::Relaxed);
    }
}

#[test]
fn unique_messages_are_mined_sequentially() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_unique(&dir, 60_000);
    let adaptive =
        mine(&request(&path, Strategy::Adaptive { chunk_bytes: MIB, threads: 4 }, false), &NoObserver).unwrap();
    let sequential = mine(&request(&path, Strategy::Sequential, false), &NoObserver).unwrap();
    assert_eq!(adaptive.metrics.strategy, "sequential");
    assert_eq!(adaptive.metrics.threads, 1);
    assert_eq!(adaptive.runs[0].records, 60_000);
    assert_eq!(summary(&adaptive), summary(&sequential));
}

#[test]
fn the_fallback_keeps_the_recount_identical_to_the_sequential_one() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_unique(&dir, 40_000);
    let adaptive =
        mine(&request(&path, Strategy::Adaptive { chunk_bytes: MIB, threads: 4 }, true), &NoObserver).unwrap();
    let sequential = mine(&request(&path, Strategy::Sequential, true), &NoObserver).unwrap();
    assert_eq!(adaptive.metrics.strategy, "sequential");
    assert_eq!(summary(&adaptive), summary(&sequential));
}

#[test]
fn the_fallback_does_not_count_the_input_twice_in_the_progress() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_unique(&dir, 60_000);
    let size = std::fs::metadata(&path).unwrap().len();
    let observer = Bytes(AtomicU64::new(0));
    let output = mine(&request(&path, Strategy::Adaptive { chunk_bytes: MIB, threads: 4 }, false), &observer).unwrap();
    assert_eq!(output.metrics.strategy, "sequential");
    let reported = observer.0.load(Ordering::Relaxed);
    assert!(reported >= size, "the progress ended at {reported} of {size} bytes");
    assert!(reported < size + 4096, "the input was counted twice: {reported} of {size} bytes");
}

#[test]
fn repetitive_logs_stay_chunked() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_repetitive(&dir, 80_000);
    let adaptive =
        mine(&request(&path, Strategy::Adaptive { chunk_bytes: MIB, threads: 4 }, false), &NoObserver).unwrap();
    let chunked =
        mine(&request(&path, Strategy::Chunked { chunk_bytes: MIB, threads: 4 }, false), &NoObserver).unwrap();
    assert_eq!(adaptive.metrics.strategy, "chunked");
    assert!(adaptive.metrics.chunks > 1);
    assert_eq!(summary(&adaptive), summary(&chunked));
}

#[test]
fn a_first_chunk_with_few_records_is_not_enough_to_give_up() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_unique(&dir, 8000);
    let output =
        mine(&request(&path, Strategy::Adaptive { chunk_bytes: 64 * 1024, threads: 4 }, false), &NoObserver).unwrap();
    assert!(output.metrics.chunks > 1);
    assert_eq!(output.metrics.strategy, "chunked");
}

#[test]
fn an_input_of_one_chunk_is_mined_sequentially() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_repetitive(&dir, 2000);
    let output =
        mine(&request(&path, Strategy::Adaptive { chunk_bytes: 64 * MIB, threads: 4 }, false), &NoObserver).unwrap();
    assert_eq!(output.metrics.strategy, "sequential");
}

/// Cancels the run once it has reported `limit` bytes.
struct CancelAfter {
    limit: u64,
    seen: AtomicU64,
}

impl Observer for CancelAfter {
    fn on_bytes(&self, consumed: u64) {
        self.seen.fetch_add(consumed, Ordering::Relaxed);
    }

    fn cancelled(&self) -> bool {
        self.seen.load(Ordering::Relaxed) >= self.limit
    }
}

#[test]
fn a_cancel_during_the_probe_is_reported_as_a_cancel() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_unique(&dir, 60_000);
    let observer = CancelAfter { limit: 1, seen: AtomicU64::new(0) };
    let result = mine(&request(&path, Strategy::Adaptive { chunk_bytes: MIB, threads: 4 }, false), &observer);
    assert!(matches!(result, Err(EngineError::Cancelled)), "{result:?}");
}

#[test]
fn a_cancel_after_the_fallback_is_reported_as_a_cancel() {
    let dir = tempfile::tempdir().unwrap();
    let path = write_unique(&dir, 200_000);
    let observer = CancelAfter { limit: 8 * MIB, seen: AtomicU64::new(0) };
    let result = mine(&request(&path, Strategy::Adaptive { chunk_bytes: MIB, threads: 2 }, false), &observer);
    assert!(matches!(result, Err(EngineError::Cancelled)), "{result:?}");
    let reported = observer.seen.load(Ordering::Relaxed);
    assert!(reported >= 8 * MIB, "the cancel came during the first phase: {reported} bytes");
}
