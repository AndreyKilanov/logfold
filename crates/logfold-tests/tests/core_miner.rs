#![allow(missing_docs)]

use logfold_core::*;

fn feed(miner: &mut DrainMiner, run: usize, line: &str) {
    let tok = Tokenizer::new(b" \t\n\r").unwrap();
    let mut spans = Vec::new();
    tok.tokenize(line.as_bytes(), &mut spans);
    let view = TokenView::new(line.as_bytes(), &spans);
    miner.add(run, &view, &RecordMeta { message: line.as_bytes(), timestamp: None, level: None });
}

fn texts(miner: DrainMiner) -> Vec<(String, u64)> {
    miner.freeze().into_iter().map(|t| (t.text, t.runs.iter().map(|r| r.count).sum())).collect()
}

#[test]
fn groups_and_generalizes() {
    let mut miner = DrainMiner::new(MinerConfig::default(), 1);
    for user in ["alice", "bob", "carol"] {
        feed(&mut miner, 0, &format!("user {user} failed login"));
    }
    feed(&mut miner, 0, "disk full on sda");
    let result = texts(miner);
    assert_eq!(result[0], ("user <*> failed login".to_string(), 3));
    assert_eq!(result[1], ("disk full on sda".to_string(), 1));
}

#[test]
fn numeric_tokens_route_to_wildcard() {
    let mut miner = DrainMiner::new(MinerConfig::default(), 1);
    feed(&mut miner, 0, "42 items processed");
    feed(&mut miner, 0, "43 items processed");
    let result = texts(miner);
    assert_eq!(result, vec![("<*> items processed".to_string(), 2)]);
}

#[test]
fn empty_messages_form_one_template() {
    let mut miner = DrainMiner::new(MinerConfig::default(), 1);
    feed(&mut miner, 0, "");
    feed(&mut miner, 0, "");
    assert_eq!(texts(miner), vec![(String::new(), 2)]);
}

#[test]
fn counts_are_kept_per_run() {
    let mut miner = DrainMiner::new(MinerConfig::default(), 2);
    feed(&mut miner, 0, "ready");
    feed(&mut miner, 1, "ready");
    feed(&mut miner, 1, "ready");
    let frozen = miner.freeze();
    assert_eq!(frozen.len(), 1);
    assert_eq!(frozen[0].runs[0].count, 1);
    assert_eq!(frozen[0].runs[1].count, 2);
}

#[test]
fn overflow_collects_excess_templates() {
    let cfg = MinerConfig::new(4, 0.4, 100, 2).unwrap();
    let mut miner = DrainMiner::new(cfg, 1);
    for line in ["a b c", "d e f", "g h i", "j k l"] {
        feed(&mut miner, 0, line);
    }
    assert!(miner.overflowed()[0]);
    let result = texts(miner);
    let total: u64 = result.iter().map(|(_, c)| c).sum();
    assert_eq!(total, 4);
    assert!(result.iter().any(|(t, c)| t == "<*> <*> <*>" && *c == 2));
}

#[test]
fn merge_conserves_counts_and_matches_templates() {
    let cfg = MinerConfig::default();
    let mut left = DrainMiner::new(cfg.clone(), 1);
    let mut right = DrainMiner::new(cfg, 1);
    for user in ["alice", "bob"] {
        feed(&mut left, 0, &format!("user {user} failed login"));
    }
    for user in ["carol", "dave", "erin"] {
        feed(&mut right, 0, &format!("user {user} failed login"));
    }
    feed(&mut right, 0, "disk full on sda");
    left.merge(right);
    let result = texts(left);
    assert_eq!(result[0], ("user <*> failed login".to_string(), 5));
    assert_eq!(result[1], ("disk full on sda".to_string(), 1));
}

fn next(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1_442_695_040_888_963_407);
    *state >> 33
}

/// A line with a constant first token (one big leaf per length). Every line belongs to one of 40 families that fix
/// about half of the positions; some positions draw from tiny pools (shared by many templates, so their index
/// lists are long) and the others from large pools.
fn crowded_line(state: &mut u64, length: usize) -> Vec<Box<[u8]>> {
    let family = next(state) % 40;
    let mut words: Vec<Box<[u8]>> = vec![b"-".to_vec().into()];
    for position in 1..length {
        let word = match position % 5 {
            0 => format!("s{position}x{}", next(state) % 2),
            1 => format!("m{position}x{}", next(state) % 30),
            _ if (family as usize + position) % 2 == 0 => format!("f{family}p{position}"),
            _ => format!("r{position}x{}", next(state) % 5000),
        };
        words.push(word.into_bytes().into());
    }
    words
}

#[test]
fn indexed_search_equals_the_plain_scan() {
    let mut configs_with_an_index = 0;
    let mut all_matches = 0;
    for (sim_th, seed) in [(0.4, 11_u64), (0.1, 12), (0.7, 13), (0.95, 14)] {
        let cfg = MinerConfig::new(4, sim_th, 100, 100_000).unwrap();
        let mut miner = DrainMiner::new(cfg, 1);
        let mut state = seed;
        for round in 0..6000 {
            let length = 6 + round % 14;
            let line = crowded_line(&mut state, length);
            let text = line.iter().map(|t| String::from_utf8_lossy(t).into_owned()).collect::<Vec<_>>().join(" ");
            feed(&mut miner, 0, &text);
        }
        if miner.has_indexed_leaf() {
            configs_with_an_index += 1;
        }
        let mut compared = 0;
        let mut matched = 0;
        for round in 0..4000 {
            let length = 6 + round % 14;
            let mut line = crowded_line(&mut state, length);
            if round % 3 == 0 {
                // an unseen token at a random position, and a repeated one elsewhere
                let at = 1 + (next(&mut state) as usize) % (length - 1);
                line[at] = b"never-seen".to_vec().into();
            }
            let (indexed, reference) = miner.match_both_ways(&line);
            assert_eq!(indexed, reference, "sim_th {sim_th}, probe {round}");
            compared += 1;
            matched += usize::from(indexed.is_some());
        }
        assert_eq!(compared, 4000);
        all_matches += matched;
    }
    assert!(all_matches > 500, "the probes must find matches too ({all_matches})");
    assert!(configs_with_an_index >= 3, "most configurations must have leaves with an index");
}

#[test]
fn identical_input_gives_identical_output() {
    let run = || {
        let mut miner = DrainMiner::new(MinerConfig::default(), 1);
        for i in 0..200 {
            feed(&mut miner, 0, &format!("worker w{} handled request for tenant t{}", i % 7, i % 3));
            feed(&mut miner, 0, &format!("cache miss key={}", i % 11));
        }
        texts(miner)
    };
    assert_eq!(run(), run());
}
