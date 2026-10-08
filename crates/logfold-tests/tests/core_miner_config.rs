#![allow(missing_docs)]

use logfold_core::MinerConfig;

#[test]
fn the_default_is_what_the_constructor_builds_from_the_documented_values() {
    let built = MinerConfig::new(4, 0.4, 100, 100_000).unwrap();
    assert_eq!(format!("{:?}", MinerConfig::default()), format!("{built:?}"));
}
