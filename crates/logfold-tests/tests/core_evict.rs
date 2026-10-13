#![allow(missing_docs)]

//! A miner that evicts: the least recently used templates make room for new ones, the counts are pooled so that the
//! totals add up, the number of templates never passes the limit, and the tree stays consistent.

mod common;

use common::{feed, lines};
use logfold_core::{DrainMiner, MinerConfig, OnFull};
use proptest::prelude::*;

fn evicting(max_templates: usize) -> DrainMiner {
    DrainMiner::new(MinerConfig::new(4, 0.4, 100, max_templates).unwrap().with_on_full(OnFull::Evict), 1)
}

fn pooling(max_templates: usize) -> DrainMiner {
    DrainMiner::new(MinerConfig::new(4, 0.4, 100, max_templates).unwrap(), 1)
}

fn line(n: usize) -> String {
    format!("w{n}x w{n}y w{n}z")
}

fn texts(miner: &DrainMiner) -> Vec<String> {
    miner.templates().into_iter().map(|template| template.text).collect()
}

fn total(miner: &DrainMiner) -> u64 {
    miner.templates().iter().map(|template| template.total()).sum()
}

#[test]
fn the_template_that_was_used_least_recently_is_the_one_that_goes() {
    let mut miner = evicting(10);
    let mut index = 0;
    let mut add = |miner: &mut DrainMiner, text: &str| {
        feed(miner, 0, text, index);
        index += 1;
    };
    for n in 0..10 {
        add(&mut miner, &line(n));
    }
    for n in 1..10 {
        add(&mut miner, &line(n));
    }
    assert_eq!(miner.cluster_count(), 10);
    add(&mut miner, &line(10));

    let present = texts(&miner);
    assert!(!present.contains(&line(0)), "the template of line 0 was the least recently used");
    for n in 1..=10 {
        assert!(present.contains(&line(n)), "line {n} must stay");
    }
    assert_eq!(miner.evicted(), &[1]);
    assert_eq!(miner.cluster_count(), 10);
    assert!(miner.overflowed()[0]);
    let pooled = miner.templates().into_iter().find(|template| template.text == "<*> <*> <*>").unwrap();
    assert_eq!(pooled.total(), 1, "the one record of line 0 is in the catch-all template of its length");
    assert_eq!(total(&miner), 20);
}

#[test]
fn a_miner_that_pools_keeps_the_old_templates_and_drops_the_new_shape() {
    let mut miner = pooling(10);
    for n in 0..11 {
        feed(&mut miner, 0, &line(n), n);
    }
    let present = texts(&miner);
    assert!(present.contains(&line(0)));
    assert!(!present.contains(&line(10)));
    assert_eq!(miner.evicted(), &[0]);
}

#[test]
fn a_tenth_of_the_limit_goes_at_a_time() {
    let mut miner = evicting(50);
    for n in 0..51 {
        feed(&mut miner, 0, &line(n), n);
    }
    assert_eq!(miner.evicted(), &[5]);
    assert_eq!(miner.cluster_count(), 46);
    assert_eq!(total(&miner), 51);
}

#[test]
fn the_texts_of_new_templates_skip_the_ones_that_went() {
    let mut miner = evicting(10);
    for n in 0..5 {
        feed(&mut miner, 0, &line(n), n);
    }
    assert_eq!(miner.take_new_texts().len(), 5);
    for n in 5..12 {
        feed(&mut miner, 0, &line(n), n);
    }
    let fresh = miner.take_new_texts();
    let alive = texts(&miner);
    assert!(fresh.iter().all(|text| alive.contains(text)), "{fresh:?} against {alive:?}");
    assert!(fresh.contains(&line(11)));
    assert!(!fresh.contains(&line(0)));
    assert!(miner.take_new_texts().is_empty());
}

#[test]
fn a_loaded_miner_evicts_its_oldest_templates_first() {
    let mut first = evicting(10);
    for n in 0..10 {
        feed(&mut first, 0, &line(n), n);
    }
    let mut loaded = DrainMiner::from_snapshot(first.snapshot(), 1).unwrap().with_on_full(OnFull::Evict);
    loaded.mark_reported();
    feed(&mut loaded, 0, &line(10), 10);
    let present = texts(&loaded);
    assert!(!present.contains(&line(0)));
    assert!(present.contains(&line(1)));
    assert_eq!(loaded.evicted(), &[1]);
    let saved = loaded.snapshot();
    let kept: u64 =
        saved.clusters.iter().chain(saved.overflow.iter().map(|(_, cluster)| cluster)).map(|c| c.history.count).sum();
    assert_eq!(kept, 11, "the history of the evicted template joined the catch-all template");
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(96))]

    #[test]
    fn the_limit_holds_and_the_totals_add_up(stream in lines(300), limit in 1usize..40) {
        let mut miner = evicting(limit);
        for (index, text) in stream.iter().enumerate() {
            feed(&mut miner, 0, text, index);
            prop_assert!(miner.cluster_count() <= limit);
        }
        prop_assert_eq!(total(&miner), stream.len() as u64);
        prop_assert_eq!(miner.snapshot().clusters.len(), miner.cluster_count());
    }

    #[test]
    fn the_same_stream_gives_the_same_miner(stream in lines(200), limit in 1usize..30) {
        let run = || {
            let mut miner = evicting(limit);
            for (index, text) in stream.iter().enumerate() {
                feed(&mut miner, 0, text, index);
            }
            (miner.snapshot(), miner.evicted().to_vec())
        };
        prop_assert_eq!(run(), run());
    }

    #[test]
    fn the_tree_is_consistent_after_evictions(stream in lines(300), probe in lines(60), limit in 2usize..30) {
        let mut miner = evicting(limit);
        for (index, text) in stream.iter().enumerate() {
            feed(&mut miner, 0, text, index);
        }
        for text in &probe {
            let tokens: Vec<Box<[u8]>> = text.split(' ').map(|token| token.as_bytes().into()).collect();
            let (indexed, plain) = miner.match_both_ways(&tokens);
            prop_assert_eq!(indexed, plain);
            let (indexed, plain) = miner.fallback_both_ways(&tokens);
            prop_assert_eq!(indexed, plain);
            let (indexed, plain) = miner.exact_fallback_both_ways(&tokens);
            prop_assert_eq!(indexed, plain);
        }
        let rebuilt = DrainMiner::from_snapshot(miner.snapshot(), 1);
        prop_assert!(rebuilt.is_ok(), "an evicted miner must make a valid snapshot");
    }

    #[test]
    fn a_limit_that_is_never_reached_changes_nothing(stream in lines(100)) {
        let mut evicting_miner = evicting(100_000);
        let mut pooling_miner = pooling(100_000);
        for (index, text) in stream.iter().enumerate() {
            feed(&mut evicting_miner, 0, text, index);
            feed(&mut pooling_miner, 0, text, index);
        }
        prop_assert_eq!(evicting_miner.snapshot(), pooling_miner.snapshot());
        prop_assert_eq!(evicting_miner.evicted(), &[0]);
    }
}
