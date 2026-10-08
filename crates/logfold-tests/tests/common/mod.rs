//! Generators and helpers shared by the property tests.

#![allow(dead_code, reason = "every test crate uses a part of the helpers")]

use logfold_core::{DrainMiner, Level, MinerConfig, RecordMeta, TokenView, Tokenizer};
use proptest::prelude::*;

pub const DELIMITERS: &[u8] = b" \t\n\r";

/// A token: a few constant words that make templates, numbers and identifiers that vary.
pub fn word() -> impl Strategy<Value = String> {
    prop_oneof![3 => "[a-d]{1,3}", 2 => "[0-9]{1,4}", 1 => "[a-z]{1,2}[0-9]{1,3}"]
}

/// A log message of one to nine tokens.
pub fn line() -> impl Strategy<Value = String> {
    prop::collection::vec(word(), 1..10).prop_map(|words| words.join(" "))
}

/// Between one and `max - 1` messages.
pub fn lines(max: usize) -> impl Strategy<Value = Vec<String>> {
    prop::collection::vec(line(), 1..max)
}

/// Valid miner parameters, including tiny template limits that force the overflow template.
pub fn config() -> impl Strategy<Value = MinerConfig> {
    (
        3usize..=6,
        prop::sample::select(vec![0.0, 0.1, 0.4, 0.7, 1.0]),
        1usize..=6,
        prop_oneof![Just(100_000usize), 1usize..30],
    )
        .prop_filter_map("invalid miner parameters", |(depth, sim_th, children, templates)| {
            MinerConfig::new(depth, sim_th, children, templates).ok()
        })
}

/// Adds one message to run `run`; `index` decides its time and level.
pub fn feed(miner: &mut DrainMiner, run: usize, line: &str, index: usize) {
    let tokenizer = Tokenizer::new(DELIMITERS).unwrap();
    let mut spans = Vec::new();
    tokenizer.tokenize(line.as_bytes(), &mut spans);
    let view = TokenView::new(line.as_bytes(), &spans);
    let level = [Level::Info, Level::Warn, Level::Error][index % 3];
    let record = RecordMeta { message: line.as_bytes(), timestamp: Some(1_000_000 + index as i64), level: Some(level) };
    miner.add(run, &view, &record);
}

/// Adds `stream` to `miner` as run 0; the first message has position `from` in the whole stream.
pub fn train(miner: &mut DrainMiner, stream: &[String], from: usize) {
    for (offset, line) in stream.iter().enumerate() {
        feed(miner, 0, line, from + offset);
    }
}

/// A miner of one run that has seen `stream`.
pub fn mined(config: &MinerConfig, stream: &[String]) -> DrainMiner {
    let mut miner = DrainMiner::new(config.clone(), 1);
    train(&mut miner, stream, 0);
    miner
}
