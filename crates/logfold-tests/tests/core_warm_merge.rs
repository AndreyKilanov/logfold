#![allow(missing_docs)]

//! The exact search of a length relies on the list of the templates with few literal tokens; a warm merge, which
//! generalizes the templates of the seed in place, must keep that list complete.

use logfold_core::{DrainMiner, MinerConfig, RecordMeta, TokenView, Tokenizer};

fn feed(miner: &mut DrainMiner, line: &str) {
    let tokenizer = Tokenizer::new(b" \t\n\r").unwrap();
    let mut spans = Vec::new();
    tokenizer.tokenize(line.as_bytes(), &mut spans);
    let view = TokenView::new(line.as_bytes(), &spans);
    miner.add(0, &view, &RecordMeta { message: line.as_bytes(), timestamp: None, level: None });
}

fn token(text: &str) -> Box<[u8]> {
    text.as_bytes().into()
}

#[test]
fn a_seed_template_that_a_warm_merge_leaves_with_one_literal_is_still_found_exactly() {
    let mut seed = DrainMiner::new(MinerConfig::new(4, 0.1, 100, 100_000).unwrap(), 1);
    for i in 0..40 {
        feed(&mut seed, &format!("c{i}t0 c{i}t1 c{i}t2 c{i}t3 c{i}t4 c{i}t5"));
    }
    let seed_len = seed.cluster_count();
    let mut worker = seed.warm_copy();
    for i in 0..40 {
        feed(&mut worker, &format!("c{i}t0 u{i}a u{i}b u{i}c u{i}d u{i}e"));
    }
    let mut merged = seed.clone();
    merged.merge_warm(worker, seed_len);

    for i in 0..40 {
        let probe = [token(&format!("c{i}t0")), token("q1"), token("q2"), token("q3"), token("q4"), token("q5")];
        let (indexed, plain) = merged.exact_fallback_both_ways(&probe);
        assert!(plain.is_some(), "probe {i}: the template with one literal fits");
        assert_eq!(indexed, plain, "probe {i}");
    }
}
