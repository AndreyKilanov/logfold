#![allow(missing_docs)]

use logfold_core::{DrainMiner, MinerConfig};
use logfold_io::{State, StateError, StateHeader};

fn state() -> State {
    let snapshot = DrainMiner::new(MinerConfig::default(), 1).snapshot();
    let header = StateHeader {
        algo_version: 3,
        contract: 9,
        logfold_version: "0.4.0".into(),
        config_hash: "abc".into(),
        masks: "default".into(),
        format: "plain".into(),
    };
    State { header, snapshot }
}

#[test]
fn a_state_of_the_same_algorithm_and_settings_is_compatible() {
    assert!(state().ensure_compatible(3, "abc").is_ok());
}

#[test]
fn another_algorithm_version_is_incompatible() {
    let error = state().ensure_compatible(4, "abc").unwrap_err();
    assert!(matches!(&error, StateError::Incompatible(m) if m.contains("algorithm version 3, this logfold uses 4")));
}

#[test]
fn other_settings_are_incompatible() {
    let error = state().ensure_compatible(3, "xyz").unwrap_err();
    assert!(matches!(&error, StateError::Incompatible(m) if m.contains("fingerprint abc, now xyz")));
}
