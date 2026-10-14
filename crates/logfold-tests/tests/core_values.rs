#![allow(missing_docs)]

//! Distributions of the values of a position: exact counters up to the cap, logarithmic buckets for the numbers, and a
//! merge that gives the same numbers whatever the order.

use logfold_core::{Distribution, MAX_DISTINCT, MAX_VALUE_BYTES, TOP_VALUES, ValueSummary};
use proptest::prelude::*;

fn distribution(values: &[&str]) -> Distribution {
    let mut distribution = Distribution::default();
    for value in values {
        distribution.add(value.as_bytes());
    }
    distribution
}

fn within(actual: f64, expected: f64, relative: f64) -> bool {
    (actual - expected).abs() <= expected.abs() * relative
}

#[test]
fn the_top_values_are_ordered_by_count_and_then_by_bytes() {
    let summary = distribution(&["b", "a", "b", "c", "a", "b", "d"]).summary();
    assert_eq!(summary.count, 7);
    let top: Vec<(&[u8], u64)> = summary.top.iter().map(|(value, count)| (value.as_slice(), *count)).collect();
    assert_eq!(top, vec![(&b"b"[..], 3), (&b"a"[..], 2), (&b"c"[..], 1), (&b"d"[..], 1)]);
    assert_eq!(summary.distinct, 4);
    assert!(!summary.capped);
    assert_eq!(summary.other, 0);
    assert!(summary.numeric.is_none());
}

#[test]
fn only_the_ten_most_frequent_values_are_listed() {
    let mut distribution = Distribution::default();
    for value in 0..30u32 {
        for _ in 0..=value {
            distribution.add(format!("v{value:02}").as_bytes());
        }
    }
    let summary = distribution.summary();
    assert_eq!(summary.top.len(), TOP_VALUES);
    assert_eq!(summary.top[0], (b"v29".to_vec(), 30));
    assert_eq!(summary.distinct, 30);
}

#[test]
fn values_beyond_the_cap_are_counted_but_not_kept() {
    let mut distribution = Distribution::default();
    for value in 0..MAX_DISTINCT + 500 {
        distribution.add(format!("value-{value}").as_bytes());
    }
    distribution.add(b"value-0");
    let summary = distribution.summary();
    assert_eq!(summary.count, (MAX_DISTINCT + 501) as u64);
    assert_eq!(summary.distinct, MAX_DISTINCT as u64);
    assert!(summary.capped);
    assert_eq!(summary.other, 500);
    assert_eq!(summary.top[0], (b"value-0".to_vec(), 2));
}

#[test]
fn a_long_value_is_cut_and_counted_under_its_first_bytes() {
    let long = "x".repeat(200);
    let summary = distribution(&[long.as_str(), long.as_str()]).summary();
    assert_eq!(summary.top, vec![(vec![b'x'; MAX_VALUE_BYTES], 2)]);
}

#[test]
fn only_plain_decimal_numbers_are_numbers() {
    for text in ["1e5", "+1", "1.", ".5", "-", "", "0x10", "12ms", "1,5", "--1", "1.2.3", "٣"] {
        assert!(distribution(&[text]).summary().numeric.is_none(), "{text:?}");
    }
    for text in ["0", "-7", "3.14", "-0.5", "007"] {
        assert!(distribution(&[text]).summary().numeric.is_some(), "{text:?}");
    }
}

#[test]
fn the_percentiles_are_within_the_error_of_a_bucket() {
    let values: Vec<String> = (1..=1000).map(|n| n.to_string()).collect();
    let refs: Vec<&str> = values.iter().map(String::as_str).collect();
    let numeric = distribution(&refs).summary().numeric.unwrap();
    assert_eq!(numeric.count, 1000);
    assert_eq!(numeric.min, 1.0);
    assert_eq!(numeric.max, 1000.0);
    assert!(within(numeric.mean, 500.5, 1e-9));
    assert!(within(numeric.p50, 500.0, 0.03), "{}", numeric.p50);
    assert!(within(numeric.p90, 900.0, 0.03), "{}", numeric.p90);
    assert!(within(numeric.p99, 990.0, 0.03), "{}", numeric.p99);
}

#[test]
fn negative_numbers_zero_and_fractions_are_ordered() {
    let numeric = distribution(&["-100", "-10", "0", "0.5", "10", "100", "1000"]).summary().numeric.unwrap();
    assert_eq!(numeric.min, -100.0);
    assert_eq!(numeric.max, 1000.0);
    assert!(within(numeric.p50, 0.5, 0.03), "{}", numeric.p50);
    assert!(within(numeric.p90, 100.0, 0.03), "{}", numeric.p90);
    assert!(within(numeric.p99, 100.0, 0.03), "the rank of p99 of seven numbers is the sixth: {}", numeric.p99);
}

#[test]
fn a_single_number_is_its_own_percentile() {
    let numeric = distribution(&["42"]).summary().numeric.unwrap();
    assert_eq!((numeric.min, numeric.max, numeric.mean), (42.0, 42.0, 42.0));
    assert_eq!((numeric.p50, numeric.p90, numeric.p99), (42.0, 42.0, 42.0));
}

#[test]
fn merging_the_parts_in_order_equals_counting_the_whole_below_the_cap() {
    let values: Vec<String> = (0..600).map(|n| format!("{}", (n * 7) % 211)).collect();
    let refs: Vec<&str> = values.iter().map(String::as_str).collect();
    let whole = distribution(&refs).summary();
    let mut merged = distribution(&refs[..250]);
    merged.merge(&distribution(&refs[250..400]));
    merged.merge(&distribution(&refs[400..]));
    assert_eq!(merged.summary(), whole);
}

fn numbers() -> impl Strategy<Value = Vec<String>> {
    prop::collection::vec(
        prop_oneof![
            (-1_000_000i64..1_000_000).prop_map(|n| n.to_string()),
            (0u32..100_000, 0u32..1000).prop_map(|(a, b)| format!("{a}.{b}")),
            "[a-z]{1,5}",
        ],
        0..120,
    )
}

fn numbers_of(summary: &ValueSummary) -> Option<(u64, f64, f64, f64, f64)> {
    summary.numeric.as_ref().map(|n| (n.count, n.min, n.max, n.p50, n.p99))
}

proptest! {
    #[test]
    fn the_numbers_do_not_depend_on_how_the_input_is_cut_or_in_which_order_the_parts_merge(
        values in numbers(),
        cut in 0usize..120,
    ) {
        let refs: Vec<&str> = values.iter().map(String::as_str).collect();
        let at = cut.min(refs.len());
        let (head, tail) = refs.split_at(at);
        let mut forward = distribution(head);
        forward.merge(&distribution(tail));
        let mut backward = distribution(tail);
        backward.merge(&distribution(head));
        let whole = distribution(&refs);
        prop_assert_eq!(numbers_of(&forward.summary()), numbers_of(&whole.summary()));
        prop_assert_eq!(numbers_of(&backward.summary()), numbers_of(&whole.summary()));
        prop_assert_eq!(forward.summary().count, whole.summary().count);
    }
}
