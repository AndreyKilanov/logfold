#![allow(missing_docs)]
//! Invariants of the miner that must hold for any input and any valid parameters.

mod common;

use common::{config, feed, lines, mined, train};
use logfold_core::DrainMiner;
use proptest::prelude::*;

proptest! {
    #![proptest_config(ProptestConfig::with_cases(64))]

    #[test]
    fn every_record_is_counted_once_in_its_run(config in config(), stream in lines(300), runs in 1usize..=3) {
        let mut miner = DrainMiner::new(config, runs);
        for (index, line) in stream.iter().enumerate() {
            feed(&mut miner, index % runs, line, index);
        }
        let frozen = miner.freeze();
        for run in 0..runs {
            let expected = (0..stream.len()).filter(|index| index % runs == run).count() as u64;
            let counted: u64 = frozen.iter().map(|template| template.runs[run].count).sum();
            prop_assert_eq!(counted, expected, "run {}", run);
        }
    }

    #[test]
    fn the_same_stream_gives_the_same_snapshot(config in config(), stream in lines(200)) {
        prop_assert_eq!(mined(&config, &stream).snapshot(), mined(&config, &stream).snapshot());
    }

    #[test]
    fn load_then_save_is_the_identity(config in config(), stream in lines(200)) {
        let snapshot = mined(&config, &stream).snapshot();
        let rebuilt = DrainMiner::from_snapshot(snapshot.clone(), 1).unwrap();
        prop_assert_eq!(rebuilt.snapshot(), snapshot);
    }

    #[test]
    fn a_resumed_run_gives_the_tree_of_an_uninterrupted_run(
        config in config(),
        stream in lines(300),
        cut in any::<prop::sample::Index>(),
    ) {
        let split = cut.index(stream.len() + 1);
        let first = mined(&config, &stream[..split]);
        let mut resumed = DrainMiner::from_snapshot(first.snapshot(), 1).unwrap();
        train(&mut resumed, &stream[split..], split);
        prop_assert_eq!(resumed.snapshot(), mined(&config, &stream).snapshot());
    }
}
