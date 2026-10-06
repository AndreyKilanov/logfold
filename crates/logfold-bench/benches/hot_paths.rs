//! Criterion benchmarks of the hot paths: framing, masking, tokenizing and mining.
//!
//! Set `LOGFOLD_BENCH_FILE` to a log file; its first 20 MB are used. Without it a small synthetic sample is generated.
#![allow(missing_docs)]

use std::fs::File;
use std::io::Read;

use criterion::{Criterion, Throughput, black_box, criterion_group, criterion_main};
use logfold_core::{
    DrainMiner, MaskScratch, MinerConfig, RecordMeta, RuleMasker, TokenView, Tokenizer, default_mask_rules,
};
use logfold_io::{CompiledFormat, FormatConfig, FormatSpec, LineReader, ScanWindow, scan_records};

fn sample() -> Vec<u8> {
    if let Ok(path) = std::env::var("LOGFOLD_BENCH_FILE") {
        let mut data = Vec::new();
        File::open(path).expect("bench file").take(20 << 20).read_to_end(&mut data).expect("read");
        if let Some(end) = data.iter().rposition(|&b| b == b'\n') {
            data.truncate(end + 1);
        }
        return data;
    }
    let mut out = String::new();
    for i in 0..200_000u32 {
        out.push_str(&format!(
            "2026-10-04T12:{:02}:{:02}Z INFO request {} from 10.0.{}.{} took {}ms status={}\n",
            (i / 60) % 60,
            i % 60,
            i * 7919 % 100_000,
            i % 255,
            i % 200,
            i % 900,
            200 + (i % 3) * 100
        ));
    }
    out.into_bytes()
}

fn lines_of(data: &[u8]) -> Vec<&[u8]> {
    data.split(|&b| b == b'\n').filter(|l| !l.is_empty()).collect()
}

fn benches(c: &mut Criterion) {
    let data = sample();
    let lines = lines_of(&data);
    let masker = RuleMasker::new(&default_mask_rules()).unwrap();
    let tokenizer = Tokenizer::new(b" \t\n\r").unwrap();

    let mut group = c.benchmark_group("stages");
    group.throughput(Throughput::Bytes(data.len() as u64));
    group.sample_size(10);

    group.bench_function("frame_lines", |b| {
        let format = CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Plain { record_start: None },
            ts_format: None,
            multiline: false,
        })
        .unwrap();
        b.iter(|| {
            let mut count = 0usize;
            scan_records(
                LineReader::new(black_box(&data[..]), 0),
                &format,
                ScanWindow::whole(),
                |record| count += record.message.len(),
                |_| true,
            )
            .unwrap();
            count
        })
    });

    group.bench_function("mask", |b| {
        let mut scratch = MaskScratch::default();
        b.iter(|| {
            let mut total = 0usize;
            for line in &lines {
                total += masker.mask(black_box(line), &mut scratch).len();
            }
            total
        })
    });

    let masked: Vec<Vec<u8>> = {
        let mut scratch = MaskScratch::default();
        lines.iter().map(|l| masker.mask(l, &mut scratch).to_vec()).collect()
    };

    group.bench_function("tokenize", |b| {
        let mut spans = Vec::new();
        b.iter(|| {
            let mut total = 0usize;
            for line in &masked {
                tokenizer.tokenize(black_box(line), &mut spans);
                total += spans.len();
            }
            total
        })
    });

    group.bench_function("mine", |b| {
        let mut spans = Vec::new();
        b.iter(|| {
            let mut miner = DrainMiner::new(MinerConfig::default(), 1);
            for (line, raw) in masked.iter().zip(lines.iter()) {
                tokenizer.tokenize(line, &mut spans);
                let tokens = TokenView::new(line, &spans);
                miner.add(0, &tokens, &RecordMeta { message: raw, timestamp: None, level: None });
            }
            miner.cluster_count()
        })
    });
    group.finish();
}

criterion_group!(hot_paths, benches);
criterion_main!(hot_paths);
