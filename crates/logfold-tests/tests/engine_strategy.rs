#![allow(missing_docs)]

use logfold_engine::{DEFAULT_CHUNK_BYTES, EngineError, ExecutionStrategy};

#[test]
fn the_sequential_strategy_ignores_its_parameters() {
    assert!(matches!(
        ExecutionStrategy::from_name("sequential", Some(1), Some(8)).unwrap(),
        ExecutionStrategy::Sequential
    ));
}

#[test]
fn explicit_parameters_are_kept() {
    match ExecutionStrategy::from_name("chunked", Some(4096), Some(3)).unwrap() {
        ExecutionStrategy::Chunked { chunk_bytes, threads } => assert_eq!((chunk_bytes, threads), (4096, 3)),
        other => panic!("{other:?}"),
    }
    match ExecutionStrategy::from_name("adaptive", Some(4096), Some(3)).unwrap() {
        ExecutionStrategy::Adaptive { chunk_bytes, threads } => assert_eq!((chunk_bytes, threads), (4096, 3)),
        other => panic!("{other:?}"),
    }
}

#[test]
fn missing_parameters_get_defaults() {
    match ExecutionStrategy::from_name("chunked", None, None).unwrap() {
        ExecutionStrategy::Chunked { chunk_bytes, threads } => {
            assert_eq!(chunk_bytes, DEFAULT_CHUNK_BYTES);
            assert!(threads >= 1);
        }
        other => panic!("{other:?}"),
    }
}

#[test]
fn an_unknown_name_is_a_config_error() {
    let error = ExecutionStrategy::from_name("parallel", None, None).unwrap_err();
    assert!(matches!(&error, EngineError::Config(message) if message == "unknown strategy 'parallel'"), "{error}");
}
