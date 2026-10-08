//! The snapshot of a miner: a round trip, an exact continuation, and the refusal of damaged snapshots.

use logfold_core::*;

const TOKENIZER_DELIMITERS: &[u8] = b" \t\n\r";

fn next(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1_442_695_040_888_963_407);
    *state >> 33
}

fn feed(miner: &mut DrainMiner, run: usize, line: &str, timestamp: i64, level: Level) {
    let tokenizer = Tokenizer::new(TOKENIZER_DELIMITERS).unwrap();
    let mut spans = Vec::new();
    tokenizer.tokenize(line.as_bytes(), &mut spans);
    let view = TokenView::new(line.as_bytes(), &spans);
    miner.add(run, &view, &RecordMeta { message: line.as_bytes(), timestamp: Some(timestamp), level: Some(level) });
}

/// A deterministic stream of messages: several lengths, tokens with digits, families that generalize, and a big leaf
/// with a constant first token (it gets an inverted index).
fn lines(count: usize, seed: u64) -> Vec<String> {
    let mut state = seed;
    let mut out = Vec::with_capacity(count);
    for round in 0..count {
        let line = match next(&mut state) % 4 {
            0 => format!("user u{} logged in from host h{}", next(&mut state) % 50, next(&mut state) % 7),
            1 => format!("cache miss for key k{}", next(&mut state) % 400),
            2 => {
                let length = 6 + round % 9;
                let family = next(&mut state) % 30;
                let mut words = vec!["-".to_string()];
                for position in 1..length {
                    words.push(match position % 4 {
                        0 => format!("s{position}x{}", next(&mut state) % 2),
                        1 => format!("m{position}x{}", next(&mut state) % 20),
                        _ if (family as usize + position).is_multiple_of(2) => format!("f{family}p{position}"),
                        _ => format!("r{position}x{}", next(&mut state) % 3000),
                    });
                }
                words.join(" ")
            }
            _ => format!("job {} finished with code {}", next(&mut state) % 99, next(&mut state) % 3),
        };
        out.push(line);
    }
    out
}

fn mine(config: &MinerConfig, stream: &[String], from: usize) -> DrainMiner {
    let mut miner = DrainMiner::new(config.clone(), 1);
    train(&mut miner, stream, from);
    miner
}

fn train(miner: &mut DrainMiner, stream: &[String], from: usize) {
    for (offset, line) in stream.iter().enumerate() {
        let index = from + offset;
        let level = [Level::Info, Level::Warn, Level::Error][index % 3];
        feed(miner, 0, line, 1_000_000 + index as i64, level);
    }
}

fn configs() -> Vec<MinerConfig> {
    vec![
        MinerConfig::default(),
        MinerConfig::new(4, 0.1, 100, 100_000).unwrap(),
        MinerConfig::new(5, 0.7, 3, 100_000).unwrap(),
        MinerConfig::new(3, 0.4, 100, 60).unwrap(),
    ]
}

#[test]
fn the_snapshot_of_an_empty_miner_round_trips() {
    let miner = DrainMiner::new(MinerConfig::default(), 1);
    let snapshot = miner.snapshot();
    assert!(snapshot.nodes.is_empty() && snapshot.clusters.is_empty());
    let rebuilt = DrainMiner::from_snapshot(snapshot.clone(), 1).unwrap();
    assert_eq!(rebuilt.snapshot(), snapshot);
}

#[test]
fn a_snapshot_round_trips_and_is_deterministic() {
    let stream = lines(3000, 5);
    for config in configs() {
        let miner = mine(&config, &stream, 0);
        let snapshot = miner.snapshot();
        assert_eq!(snapshot, miner.snapshot(), "taking a snapshot changes nothing");
        assert_eq!(snapshot, mine(&config, &stream, 0).snapshot(), "the same input gives the same snapshot");
        let rebuilt = DrainMiner::from_snapshot(snapshot.clone(), 1).unwrap();
        assert_eq!(rebuilt.snapshot(), snapshot, "load then save is the identity");
    }
}

#[test]
fn the_snapshot_has_a_big_leaf_and_a_generalized_template() {
    let stream = lines(3000, 5);
    let miner = mine(&MinerConfig::default(), &stream, 0);
    assert!(miner.has_indexed_leaf(), "the stream is meant to build an inverted index");
    let snapshot = miner.snapshot();
    assert!(snapshot.clusters.iter().any(|c| c.tokens.iter().any(|t| &**t == WILDCARD)));
}

#[test]
fn a_resumed_run_gives_the_tree_of_an_uninterrupted_run() {
    let stream = lines(6000, 7);
    for config in configs() {
        let whole = mine(&config, &stream, 0).snapshot();
        for split in [0, 1, 700, 2999, 5999, 6000] {
            let first = mine(&config, &stream[..split], 0);
            let mut resumed = DrainMiner::from_snapshot(first.snapshot(), 1).unwrap();
            train(&mut resumed, &stream[split..], split);
            assert_eq!(resumed.snapshot(), whole, "split at {split}, depth {}", config.snapshot_hint());
        }
    }
}

#[test]
fn a_resumed_miner_matches_like_the_original() {
    let stream = lines(4000, 9);
    let config = MinerConfig::default();
    let original = mine(&config, &stream, 0);
    let resumed = DrainMiner::from_snapshot(original.snapshot(), 1).unwrap();
    let probes = lines(500, 99);
    let tokenizer = Tokenizer::new(TOKENIZER_DELIMITERS).unwrap();
    for probe in &probes {
        let mut spans = Vec::new();
        tokenizer.tokenize(probe.as_bytes(), &mut spans);
        let view = TokenView::new(probe.as_bytes(), &spans);
        assert_eq!(original.assign(&view), resumed.assign(&view), "probe {probe}");
    }
}

#[test]
fn a_loaded_miner_starts_a_run_with_empty_statistics() {
    let stream = lines(1000, 3);
    let saved = mine(&MinerConfig::default(), &stream, 0);
    let history: u64 = saved.snapshot().clusters.iter().map(|c| c.history.count).sum();
    assert_eq!(history, 1000);
    let mut loaded = DrainMiner::from_snapshot(saved.snapshot(), 1).unwrap();
    for template in loaded.clone().freeze() {
        assert_eq!(template.total(), 0, "the earlier runs are not part of the new run");
    }
    train(&mut loaded, &lines(100, 4), 1000);
    let this_run: u64 = loaded.clone().freeze().iter().map(FrozenTemplate::total).sum();
    assert_eq!(this_run, 100);
    let all: u64 = loaded.snapshot().clusters.iter().map(|c| c.history.count).sum();
    assert_eq!(all, 1100, "a new snapshot adds the run to the history");
}

#[test]
fn the_history_keeps_levels_and_times_but_no_example() {
    let mut miner = DrainMiner::new(MinerConfig::default(), 1);
    feed(&mut miner, 0, "disk full on volume 1", 50, Level::Error);
    feed(&mut miner, 0, "disk full on volume 2", 10, Level::Warn);
    let snapshot = miner.snapshot();
    assert_eq!(snapshot.clusters.len(), 1);
    let history = snapshot.clusters[0].history;
    assert_eq!(history.count, 2);
    assert_eq!((history.first, history.last), (10, 50));
    assert_eq!(history.levels[Level::Error.rank()], 1);
    assert_eq!(history.levels[Level::Warn.rank()], 1);
}

/// Damages a snapshot and checks that loading it fails for the reason named by `reason`.
fn refused(mut snapshot: MinerSnapshot, reason: &str, damage: impl FnOnce(&mut MinerSnapshot)) -> bool {
    damage(&mut snapshot);
    match DrainMiner::from_snapshot(snapshot, 1) {
        Err(CoreError::InvalidState(message)) => {
            assert!(message.contains(reason), "refused for another reason: {message} (expected {reason})");
            true
        }
        Err(other) => panic!("another kind of error: {other}"),
        Ok(_) => false,
    }
}

fn good() -> MinerSnapshot {
    mine(&MinerConfig::default(), &lines(2500, 11), 0).snapshot()
}

fn overflowing() -> MinerSnapshot {
    mine(&MinerConfig::new(3, 0.4, 100, 40).unwrap(), &lines(2500, 11), 0).snapshot()
}

#[test]
fn damaged_parameters_are_refused() {
    assert!(refused(good(), "depth must be at least 3", |s| s.depth = 2));
    assert!(refused(good(), "similarity threshold", |s| s.threshold_micro = 1_000_001));
    assert!(refused(good(), "max_children and max_templates", |s| s.max_children = 0));
    assert!(refused(good(), "max_children and max_templates", |s| s.max_templates = 0));
    assert!(refused(good(), "exceed max_templates", |s| s.max_templates = 1));
    assert!(
        matches!(DrainMiner::from_snapshot(good(), 0), Err(CoreError::InvalidState(ref m)) if m.contains("at least one run"))
    );
    assert!(DrainMiner::from_snapshot(good(), 1).is_ok(), "the undamaged snapshot loads");
}

#[test]
fn a_damaged_shape_of_the_tree_is_refused() {
    assert!(refused(good(), "roots are not ordered", |s| s.roots.swap(0, 1)));
    assert!(refused(good(), "root points outside", |s| s.roots[0].1 = u32::MAX));
    assert!(refused(good(), "cannot be reached", |s| s
        .nodes
        .push(NodeSnapshot { children: vec![], clusters: vec![] })));
    assert!(refused(good(), "reached twice", |s| {
        let node = s.nodes.iter_mut().find(|n| n.children.len() >= 2).unwrap();
        node.children[1].1 = node.children[0].1;
    }));
    assert!(refused(good(), "not ordered by token", |s| {
        let node = s.nodes.iter_mut().find(|n| n.children.len() >= 2).unwrap();
        node.children.reverse();
    }));
    assert!(refused(good(), "child points outside", |s| {
        let node = s.nodes.iter_mut().find(|n| !n.children.is_empty()).unwrap();
        node.children[0].1 = u32::MAX;
    }));
    assert!(refused(good(), "inner node holds templates", |s| {
        let node = s.nodes.iter_mut().find(|n| !n.children.is_empty()).unwrap();
        node.clusters.push(0);
    }));
    assert!(refused(good(), "leaf has children", |s| {
        let leaf = s.nodes.iter_mut().find(|n| n.children.is_empty() && !n.clusters.is_empty()).unwrap();
        leaf.children.push((b"x".to_vec().into(), 0));
    }));
}

#[test]
fn damaged_templates_are_refused() {
    assert!(refused(good(), "in no leaf", |s| {
        let leaf = s.nodes.iter_mut().find(|n| n.children.is_empty() && !n.clusters.is_empty()).unwrap();
        leaf.clusters.pop();
    }));
    assert!(refused(good(), "in two leaves", |s| {
        let leaf_with_two = s.nodes.iter().position(|n| n.children.is_empty() && n.clusters.len() >= 2).unwrap();
        let id = s.nodes[leaf_with_two].clusters[0];
        let other = s
            .nodes
            .iter()
            .position(|n| n.children.is_empty() && !n.clusters.is_empty() && !std::ptr::eq(n, &s.nodes[leaf_with_two]));
        s.nodes[other.unwrap()].clusters.push(id);
    }));
    assert!(refused(good(), "does not exist", |s| {
        s.nodes.iter_mut().find(|n| n.children.is_empty() && !n.clusters.is_empty()).unwrap().clusters.push(u32::MAX);
    }));
    assert!(refused(good(), "another length", |s| {
        let cluster = s.clusters.iter_mut().find(|c| c.tokens.len() > 2).unwrap();
        cluster.tokens.pop();
    }));
    assert!(refused(good(), "empty token", |s| s.clusters[0].tokens[0] = Box::from(&b""[..])));
}

#[test]
fn a_template_that_cannot_follow_its_path_is_refused() {
    assert!(refused(good(), "follow the path", |s| {
        let leaf_path = {
            let mut found = None;
            for node in &s.nodes {
                for (key, child) in &node.children {
                    let child_node = &s.nodes[*child as usize];
                    if &**key != WILDCARD && child_node.children.is_empty() && !child_node.clusters.is_empty() {
                        found = Some((child_node.clusters[0], key.clone()));
                    }
                }
            }
            found.expect("a leaf below a literal token")
        };
        let cluster = &mut s.clusters[leaf_path.0 as usize];
        let position = cluster.tokens.iter().position(|t| **t == *leaf_path.1).expect("the token of the path");
        cluster.tokens[position] = Box::from(&b"never-on-this-path"[..]);
    }));
}

#[test]
fn a_literal_child_with_a_digit_is_refused() {
    assert!(refused(good(), "token with a digit", |s| {
        let node = s.nodes.iter_mut().find(|n| !n.children.is_empty()).unwrap();
        node.children[0].0 = Box::from(&b"a1"[..]);
    }));
}

#[test]
fn damaged_overflow_templates_are_refused() {
    let snapshot = overflowing();
    assert!(!snapshot.overflow.is_empty(), "the stream is meant to overflow the templates");
    assert!(DrainMiner::from_snapshot(snapshot.clone(), 1).is_ok());
    assert!(refused(snapshot.clone(), "overflow template", |s| s.overflow[0].1.tokens[0] = Box::from(&b"word"[..])));
    assert!(refused(snapshot, "overflow template", |s| s.overflow[0].0 += 1000));
}

#[test]
fn an_overflowing_miner_resumes_exactly() {
    let stream = lines(2500, 11);
    let config = MinerConfig::new(3, 0.4, 100, 40).unwrap();
    let whole = mine(&config, &stream, 0).snapshot();
    let first = mine(&config, &stream[..1200], 0);
    let mut resumed = DrainMiner::from_snapshot(first.snapshot(), 1).unwrap();
    train(&mut resumed, &stream[1200..], 1200);
    assert_eq!(resumed.snapshot(), whole);
}

#[test]
fn a_crafted_history_cannot_overflow_a_count() {
    let mut snapshot = good();
    snapshot.clusters[0].history.count = u64::MAX;
    snapshot.clusters[0].history.levels = [u64::MAX; LEVEL_COUNT];
    let mut loaded = DrainMiner::from_snapshot(snapshot, 1).unwrap();
    train(&mut loaded, &lines(300, 21), 0);
    let again = loaded.snapshot();
    assert_eq!(again.clusters[0].history.count, u64::MAX, "the sum saturates instead of overflowing");
}

trait ConfigHint {
    fn snapshot_hint(&self) -> String;
}

impl ConfigHint for MinerConfig {
    fn snapshot_hint(&self) -> String {
        DrainMiner::new(self.clone(), 1).snapshot().depth.to_string()
    }
}
