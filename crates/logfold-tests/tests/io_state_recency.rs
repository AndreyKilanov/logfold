//! State files of a miner that evicts: the recency of the templates is saved, a state that pools is unchanged, and the
//! file that carries the ranks is refused when they are wrong.

use logfold_core::*;
use logfold_io::*;
use sha2::{Digest, Sha256};

fn feed(miner: &mut DrainMiner, line: &str, index: i64) {
    let tokenizer = Tokenizer::new(b" \t\n\r").unwrap();
    let mut spans = Vec::new();
    tokenizer.tokenize(line.as_bytes(), &mut spans);
    let view = TokenView::new(line.as_bytes(), &spans);
    let meta = RecordMeta { message: line.as_bytes(), timestamp: Some(1_000_000 + index), level: Some(Level::Info) };
    miner.add(0, &view, &meta);
}

fn line(n: usize) -> String {
    format!("shape{n}a shape{n}b shape{n}c")
}

fn evicting(limit: usize) -> DrainMiner {
    DrainMiner::new(MinerConfig::new(4, 0.4, 100, limit).unwrap().with_on_full(OnFull::Evict), 1)
}

fn state_of(snapshot: MinerSnapshot) -> State {
    let header = StateHeader {
        algo_version: 1,
        contract: 15,
        logfold_version: "0.5.0".into(),
        config_hash: "abc".into(),
        masks: "default".into(),
        format: "plain".into(),
    };
    State { header, snapshot }
}

fn forms() -> [StateFormat; 2] {
    [StateFormat::Json, StateFormat::Binary]
}

fn resigned(mut bytes: Vec<u8>, format: StateFormat) -> Vec<u8> {
    match format {
        StateFormat::Binary => {
            bytes.truncate(bytes.len() - 32);
            let digest = Sha256::digest(&bytes);
            bytes.extend_from_slice(&digest);
        }
        StateFormat::Json => {
            let end = bytes.iter().enumerate().filter(|(_, b)| **b == b'\n').nth(1).unwrap().0 + 1;
            bytes.truncate(end);
            let digest: String = Sha256::digest(&bytes).iter().map(|b| format!("{b:02x}")).collect();
            bytes.extend_from_slice(format!("{{\"sha256\":\"{digest}\"}}\n").as_bytes());
        }
    }
    bytes
}

fn worked(limit: usize, count: usize) -> DrainMiner {
    let mut miner = evicting(limit);
    for n in 0..count {
        feed(&mut miner, &line(n % 37 + n / 5), n as i64);
    }
    miner
}

#[test]
fn the_ranks_are_saved_in_both_forms_and_a_pooling_miner_has_none() {
    let miner = worked(12, 300);
    let snapshot = miner.snapshot();
    let ranks = snapshot.recency.clone().expect("a miner that evicts saves the recency");
    let mut sorted = ranks.clone();
    sorted.sort_unstable();
    assert_eq!(sorted, (0..snapshot.clusters.len() as u32).collect::<Vec<_>>());
    for format in forms() {
        let decoded =
            decode_state(&encode_state(&state_of(snapshot.clone()), format), &StateLimits::default()).unwrap();
        assert_eq!(decoded.snapshot, snapshot, "{format:?}");
    }

    let mut pooling = DrainMiner::new(MinerConfig::new(4, 0.4, 100, 12).unwrap(), 1);
    for n in 0..300 {
        feed(&mut pooling, &line(n % 37 + n / 5), n as i64);
    }
    assert_eq!(pooling.snapshot().recency, None);
}

#[test]
fn a_pooling_state_is_written_as_schema_version_one() {
    let mut pooling = DrainMiner::new(MinerConfig::default(), 1);
    feed(&mut pooling, "a b c", 0);
    let json = encode_state(&state_of(pooling.snapshot()), StateFormat::Json);
    assert!(String::from_utf8(json).unwrap().contains("\"schema_version\":1,"));
    let binary = encode_state(&state_of(pooling.snapshot()), StateFormat::Binary);
    assert_eq!(&binary[BINARY_MAGIC.len()..BINARY_MAGIC.len() + 2], &1u16.to_le_bytes());

    let evicting_state = state_of(worked(12, 50).snapshot());
    let json = encode_state(&evicting_state, StateFormat::Json);
    assert!(String::from_utf8(json).unwrap().contains("\"schema_version\":2,"));
    let binary = encode_state(&evicting_state, StateFormat::Binary);
    assert_eq!(&binary[BINARY_MAGIC.len()..BINARY_MAGIC.len() + 2], &2u16.to_le_bytes());
}

#[test]
fn saving_and_continuing_gives_the_miner_of_one_continuous_run() {
    for (limit, split) in [(10, 40), (10, 150), (25, 200), (3, 77), (1, 30)] {
        let mut continuous = evicting(limit);
        let mut first = evicting(limit);
        let lines: Vec<String> = (0..400).map(|n| line((n * 7) % 53 + n / 11)).collect();
        for (index, text) in lines.iter().enumerate() {
            feed(&mut continuous, text, index as i64);
            if index < split {
                feed(&mut first, text, index as i64);
            }
        }
        let state = state_of(first.snapshot());
        let bytes = encode_state(&state, StateFormat::Binary);
        let loaded = decode_state(&bytes, &StateLimits::default()).unwrap();
        let mut resumed = DrainMiner::from_snapshot(loaded.snapshot, 1).unwrap().with_on_full(OnFull::Evict);
        for (index, text) in lines.iter().enumerate().skip(split) {
            feed(&mut resumed, text, index as i64);
        }
        assert_eq!(resumed.snapshot(), continuous.snapshot(), "limit {limit}, saved after {split} records");
    }
}

#[test]
fn ranks_that_are_not_a_permutation_are_refused_when_the_miner_is_built() {
    let good = worked(12, 100).snapshot();
    let count = good.clusters.len() as u32;
    for bad in [vec![0; count as usize], (1..=count).collect::<Vec<_>>(), vec![0, 1]] {
        let snapshot = MinerSnapshot { recency: Some(bad), ..good.clone() };
        assert!(matches!(DrainMiner::from_snapshot(snapshot, 1), Err(CoreError::InvalidState(_))));
    }
}

#[test]
fn the_layout_and_the_ranks_must_agree() {
    let evicting_state = state_of(worked(12, 100).snapshot());
    let json = encode_state(&evicting_state, StateFormat::Json);
    let as_version_one = String::from_utf8(json).unwrap().replacen("\"schema_version\":2", "\"schema_version\":1", 1);
    let refused = decode_state(&resigned(as_version_one.into_bytes(), StateFormat::Json), &StateLimits::default());
    assert!(matches!(refused, Err(StateError::Damaged(_))), "{refused:?}");

    let pooling = DrainMiner::new(MinerConfig::default(), 1);
    let json = encode_state(&state_of(pooling.snapshot()), StateFormat::Json);
    let as_version_two = String::from_utf8(json).unwrap().replacen("\"schema_version\":1", "\"schema_version\":2", 1);
    let refused = decode_state(&resigned(as_version_two.into_bytes(), StateFormat::Json), &StateLimits::default());
    assert!(matches!(refused, Err(StateError::Damaged(_))), "{refused:?}");

    let binary = encode_state(&evicting_state, StateFormat::Binary);
    let mut shortened = binary[..binary.len() - 32 - 1].to_vec();
    shortened.extend_from_slice(&Sha256::digest(&shortened));
    assert!(decode_state(&shortened, &StateLimits::default()).is_err());
}

#[test]
fn mutated_files_with_ranks_never_panic_and_never_build_a_broken_miner() {
    let mut random = 99u64;
    let mut next = move || {
        random = random.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1_442_695_040_888_963_407);
        random >> 33
    };
    for format in forms() {
        let original = encode_state(&state_of(worked(12, 200).snapshot()), format);
        let body_end = match format {
            StateFormat::Binary => original.len() - 32,
            StateFormat::Json => original.iter().enumerate().filter(|(_, b)| **b == b'\n').nth(1).unwrap().0 + 1,
        };
        let mut refused = 0;
        for _ in 0..1500 {
            let mut bytes = original[..body_end].to_vec();
            for _ in 0..1 + next() % 3 {
                let at = next() as usize % bytes.len();
                match next() % 3 {
                    0 => bytes[at] = next() as u8,
                    1 => bytes[at] ^= 1 << (next() % 8),
                    _ => {
                        bytes.remove(at);
                    }
                }
            }
            let mut signed = bytes.clone();
            signed.extend_from_slice(&original[body_end..]);
            match decode_state(&resigned(signed, format), &StateLimits::default()) {
                Err(_) => refused += 1,
                Ok(state) => {
                    if DrainMiner::from_snapshot(state.snapshot, 1).is_err() {
                        refused += 1;
                    }
                }
            }
        }
        assert!(refused > 300, "{format:?}: most mutations must be refused ({refused})");
    }
}
