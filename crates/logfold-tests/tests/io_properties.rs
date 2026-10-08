#![allow(missing_docs)]
//! State files: whatever is saved is loaded back unchanged, and damage never produces another state.

mod common;

use common::{config, lines, mined};
use logfold_io::{State, StateFormat, StateHeader, StateLimits, decode_state, encode_state};
use proptest::prelude::*;

fn state(config: &logfold_core::MinerConfig, stream: &[String]) -> State {
    let header = StateHeader {
        algo_version: 1,
        contract: 7,
        logfold_version: "0.5.0".into(),
        config_hash: "f54245744ffb".into(),
        masks: "default".into(),
        format: "plain".into(),
    };
    State { header, snapshot: mined(config, stream).snapshot() }
}

fn format() -> impl Strategy<Value = StateFormat> {
    prop_oneof![Just(StateFormat::Json), Just(StateFormat::Binary)]
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(64))]

    #[test]
    fn what_is_saved_is_loaded_back(config in config(), stream in lines(200), format in format()) {
        let saved = state(&config, &stream);
        let loaded = decode_state(&encode_state(&saved, format), &StateLimits::default()).unwrap();
        prop_assert_eq!(loaded, saved);
    }

    #[test]
    fn json_to_binary_to_json_loses_nothing(config in config(), stream in lines(200)) {
        let saved = state(&config, &stream);
        let json = encode_state(&saved, StateFormat::Json);
        let through = decode_state(&json, &StateLimits::default()).unwrap();
        let binary = encode_state(&through, StateFormat::Binary);
        let back = decode_state(&binary, &StateLimits::default()).unwrap();
        prop_assert_eq!(encode_state(&back, StateFormat::Json), json);
    }

    #[test]
    fn a_damaged_file_never_loads_as_another_state(
        config in config(),
        stream in lines(120),
        format in format(),
        at in any::<prop::sample::Index>(),
        flip in 1u8..=255,
    ) {
        let saved = state(&config, &stream);
        let mut bytes = encode_state(&saved, format);
        let position = at.index(bytes.len());
        bytes[position] ^= flip;
        if let Ok(loaded) = decode_state(&bytes, &StateLimits::default()) {
            prop_assert_eq!(loaded, saved);
        }
    }

    #[test]
    fn a_cut_file_never_loads_as_another_state(
        config in config(),
        stream in lines(120),
        format in format(),
        at in any::<prop::sample::Index>(),
    ) {
        let saved = state(&config, &stream);
        let mut bytes = encode_state(&saved, format);
        bytes.truncate(at.index(bytes.len()));
        if let Ok(loaded) = decode_state(&bytes, &StateLimits::default()) {
            prop_assert_eq!(loaded, saved);
        }
    }
}
