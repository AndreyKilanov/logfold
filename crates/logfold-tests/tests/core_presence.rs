#![allow(missing_docs)]

//! The sets of values that tell the new from the gone ones: exact below the limits, marked above them, and the same
//! whatever the order in which the parts of the input are merged.

use std::sync::Arc;

use logfold_core::{
    Change, MAX_PER_POSITION, PresenceCollector, TOP_CHANGES, TextCollector, ValueSet, Wanted, compare_values,
    fingerprint,
};
use proptest::prelude::*;

const NAME: &str = "num";

fn set_of(values: &[(&str, usize)]) -> ValueSet {
    let mut collector = PresenceCollector::new(usize::MAX);
    for (value, times) in values {
        for _ in 0..*times {
            collector.add(0, 1, NAME, value.as_bytes());
        }
    }
    only_set(collector)
}

fn only_set(collector: PresenceCollector) -> ValueSet {
    collector.into_clusters().into_values().next().unwrap().into_iter().next().unwrap().1
}

fn keys(values: &[(&str, u64)]) -> Vec<(u64, u64)> {
    values.iter().map(|(value, count)| (fingerprint(value.as_bytes()), *count)).collect()
}

#[test]
fn the_new_and_the_gone_values_are_told_with_their_counts() {
    let before = set_of(&[("a", 1), ("b", 3), ("c", 2)]);
    let after = set_of(&[("b", 1), ("c", 5), ("d", 4), ("e", 1)]);
    let change = compare_values(&before, &after).unwrap();
    assert_eq!(change.new_distinct, 2);
    assert_eq!(change.gone_distinct, 1);
    assert_eq!(change.shared_distinct, 2);
    assert_eq!(change.distinct, (3, 4));
    assert!(!change.capped);
    let mut new = keys(&[("d", 4), ("e", 1)]);
    new.sort_by_key(|entry| std::cmp::Reverse(entry.1));
    assert_eq!(change.new, new);
    assert_eq!(change.gone, keys(&[("a", 1)]));
}

#[test]
fn the_same_values_are_no_change_even_when_their_counts_differ() {
    assert!(compare_values(&set_of(&[("a", 1), ("b", 9)]), &set_of(&[("a", 7), ("b", 1)])).is_none());
}

#[test]
fn an_empty_side_makes_every_value_of_the_other_new_or_gone() {
    let some = set_of(&[("a", 1), ("b", 1)]);
    let none = ValueSet::default();
    let appeared = compare_values(&none, &some).unwrap();
    assert_eq!((appeared.new_distinct, appeared.gone_distinct, appeared.shared_distinct), (2, 0, 0));
    let vanished = compare_values(&some, &none).unwrap();
    assert_eq!((vanished.new_distinct, vanished.gone_distinct), (0, 2));
}

#[test]
fn a_list_keeps_the_most_frequent_values_and_the_total_counts_all_of_them() {
    let names: Vec<String> = (0..25).map(|n| format!("v{n:02}")).collect();
    let values: Vec<(&str, usize)> = names.iter().enumerate().map(|(n, name)| (name.as_str(), n + 1)).collect();
    let change = compare_values(&ValueSet::default(), &set_of(&values)).unwrap();
    assert_eq!(change.new_distinct, 25);
    assert_eq!(change.new.len(), TOP_CHANGES);
    assert_eq!(change.new.iter().map(|&(_, count)| count).collect::<Vec<_>>(), (16..=25).rev().collect::<Vec<u64>>());
}

#[test]
fn a_position_over_the_limit_of_the_collector_is_marked_and_gives_no_lists() {
    let mut collector = PresenceCollector::new(5);
    for n in 0..20 {
        collector.add(0, 1, NAME, n.to_string().as_bytes());
    }
    let set = only_set(collector);
    assert!(set.capped());
    assert_eq!(set.len(), 5);
    let change: Change = compare_values(&ValueSet::default(), &set).unwrap();
    assert!(change.capped);
    assert!(change.new.is_empty() && change.gone.is_empty());
    assert_eq!(change.distinct, (0, 5));
}

#[test]
fn a_position_over_its_own_limit_is_marked_too() {
    let mut collector = PresenceCollector::new(usize::MAX);
    for n in 0..=MAX_PER_POSITION {
        collector.add(0, 1, NAME, &n.to_le_bytes());
    }
    let set = only_set(collector);
    assert!(set.capped());
    assert_eq!(set.len(), MAX_PER_POSITION);
}

#[test]
fn the_cap_of_one_position_does_not_spend_the_room_of_the_others() {
    let mut collector = PresenceCollector::new(usize::MAX);
    for n in 0..=MAX_PER_POSITION {
        collector.add(0, 1, NAME, &n.to_le_bytes());
    }
    collector.add(0, 2, NAME, b"x");
    let sets = collector.into_clusters().into_values().next().unwrap();
    assert!(sets[0].1.capped());
    assert!(!sets[1].1.capped());
}

#[test]
fn a_collector_does_not_count_a_repeated_value_twice_against_its_limit() {
    let mut collector = PresenceCollector::new(3);
    for _ in 0..100 {
        for value in ["a", "b", "c"] {
            collector.add(0, 1, NAME, value.as_bytes());
        }
    }
    let set = only_set(collector);
    assert!(!set.capped());
    assert_eq!(set.len(), 3);
}

#[test]
fn the_texts_of_the_wanted_values_only_are_kept_and_cut_to_the_limit() {
    let long = "x".repeat(200);
    let mut wanted = Wanted::new();
    wanted.insert(7, vec![((2, NAME.to_string()), vec![fingerprint(b"keep"), fingerprint(long.as_bytes())])]);
    let mut collector = TextCollector::new(Arc::new(wanted));
    for value in ["keep", "skip", long.as_str()] {
        collector.add(7, 2, NAME, value.as_bytes());
    }
    collector.add(8, 2, NAME, b"keep");
    collector.add(7, 3, NAME, b"keep");
    let found = collector.into_found();
    assert_eq!(found.len(), 1);
    let texts = &found[&7][0].1;
    assert_eq!(texts.len(), 2);
    assert_eq!(texts[&fingerprint(b"keep")], b"keep".to_vec());
    assert_eq!(texts[&fingerprint(long.as_bytes())].len(), 64);
}

proptest! {
    #[test]
    fn the_merge_of_parts_gives_the_same_change_in_any_order(
        values in proptest::collection::vec(0u8..40, 0..200),
        cuts in proptest::collection::vec(0usize..200, 0..4),
        other in proptest::collection::vec(0u8..40, 0..200),
    ) {
        let mut cuts: Vec<usize> = cuts.into_iter().map(|cut| cut.min(values.len())).collect();
        cuts.sort_unstable();
        let mut parts = Vec::new();
        let mut from = 0;
        for cut in cuts.into_iter().chain([values.len()]) {
            let mut part = PresenceCollector::new(usize::MAX);
            for value in &values[from..cut] {
                part.add(0, 1, NAME, &[*value]);
            }
            parts.push(part);
            from = cut;
        }
        let mut whole = PresenceCollector::new(usize::MAX);
        for value in &values {
            whole.add(0, 1, NAME, &[*value]);
        }
        let mut forward = PresenceCollector::new(usize::MAX);
        for part in parts.iter().cloned() {
            forward.merge(part);
        }
        let mut backward = PresenceCollector::new(usize::MAX);
        for part in parts.into_iter().rev() {
            backward.merge(part);
        }
        let mut reference = PresenceCollector::new(usize::MAX);
        for value in &other {
            reference.add(0, 1, NAME, &[*value]);
        }
        let reference = if other.is_empty() { ValueSet::default() } else { only_set(reference) };
        let tell = |collector: PresenceCollector| {
            let set = if values.is_empty() { ValueSet::default() } else { only_set(collector) };
            compare_values(&reference, &set)
        };
        let expected = tell(whole);
        prop_assert_eq!(tell(forward), expected.clone());
        prop_assert_eq!(tell(backward), expected);
    }
}
