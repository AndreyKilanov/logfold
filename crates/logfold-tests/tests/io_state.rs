//! State files: both forms round trip, are deterministic, and refuse damaged, oversized and newer files.

use std::io::Write;

use logfold_core::*;
use logfold_io::*;
use sha2::{Digest, Sha256};

fn next(state: &mut u64) -> u64 {
    *state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1_442_695_040_888_963_407);
    *state >> 33
}

fn feed(miner: &mut DrainMiner, line: &[u8], index: i64) {
    let tokenizer = Tokenizer::new(b" \t\n\r").unwrap();
    let mut spans = Vec::new();
    tokenizer.tokenize(line, &mut spans);
    let view = TokenView::new(line, &spans);
    let level = [Level::Info, Level::Warn, Level::Error][index as usize % 3];
    miner.add(0, &view, &RecordMeta { message: line, timestamp: Some(1_000_000 + index), level: Some(level) });
}

fn lines(count: usize, seed: u64) -> Vec<String> {
    let mut state = seed;
    (0..count)
        .map(|round| match next(&mut state) % 3 {
            0 => format!("user u{} logged in from host h{}", next(&mut state) % 50, next(&mut state) % 7),
            1 => format!("cache miss for key k{}", next(&mut state) % 400),
            _ => {
                let length = 5 + round % 8;
                let family = next(&mut state) % 20;
                let mut words = vec!["-".to_string()];
                for position in 1..length {
                    words.push(if (family as usize + position).is_multiple_of(2) {
                        format!("f{family}p{position}")
                    } else {
                        format!("r{position}x{}", next(&mut state) % 3000)
                    });
                }
                words.join(" ")
            }
        })
        .collect()
}

fn snapshot_of(config: &MinerConfig, count: usize) -> MinerSnapshot {
    let mut miner = DrainMiner::new(config.clone(), 1);
    for (index, line) in lines(count, 5).iter().enumerate() {
        feed(&mut miner, line.as_bytes(), index as i64);
    }
    miner.snapshot()
}

fn header() -> StateHeader {
    StateHeader {
        algo_version: 1,
        contract: 7,
        logfold_version: "0.5.0".into(),
        config_hash: "f54245744ffb".into(),
        masks: "default".into(),
        format: "app".into(),
    }
}

fn state_of(snapshot: MinerSnapshot) -> State {
    State { header: header(), snapshot }
}

fn small() -> State {
    state_of(snapshot_of(&MinerConfig::default(), 400))
}

fn forms() -> [StateFormat; 2] {
    [StateFormat::Json, StateFormat::Binary]
}

fn sha(bytes: &[u8]) -> Vec<u8> {
    Sha256::digest(bytes).to_vec()
}

/// Replaces the checksum of a state file by the checksum of its (damaged) content.
fn resigned(mut bytes: Vec<u8>, format: StateFormat) -> Vec<u8> {
    match format {
        StateFormat::Binary => {
            bytes.truncate(bytes.len() - 32);
            let digest = sha(&bytes);
            bytes.extend_from_slice(&digest);
        }
        StateFormat::Json => {
            let mut newlines = bytes.iter().enumerate().filter(|(_, b)| **b == b'\n').map(|(i, _)| i);
            let end = newlines.nth(1).expect("two lines before the checksum") + 1;
            bytes.truncate(end);
            let digest: String = sha(&bytes).iter().map(|b| format!("{b:02x}")).collect();
            bytes.extend_from_slice(format!("{{\"sha256\":\"{digest}\"}}\n").as_bytes());
        }
    }
    bytes
}

fn replaced(bytes: &[u8], from: &str, to: &str) -> Vec<u8> {
    let text = String::from_utf8(bytes.to_vec()).unwrap();
    assert_eq!(text.matches(from).count(), 1, "'{from}' must occur once");
    text.replacen(from, to, 1).into_bytes()
}

#[test]
fn both_forms_round_trip() {
    let configs = [
        MinerConfig::default(),
        MinerConfig::new(5, 0.7, 3, 100_000).unwrap(),
        MinerConfig::new(3, 0.4, 100, 40).unwrap(),
    ];
    for config in &configs {
        let state = state_of(snapshot_of(config, 3000));
        for format in forms() {
            let bytes = encode_state(&state, format);
            let decoded = decode_state(&bytes, &StateLimits::default()).unwrap();
            assert_eq!(decoded, state, "{format:?}");
            let miner = DrainMiner::from_snapshot(decoded.snapshot, 1).unwrap();
            assert_eq!(miner.snapshot(), state.snapshot, "{format:?}: the loaded miner is the saved one");
        }
    }
}

#[test]
fn an_empty_miner_round_trips() {
    let state = state_of(DrainMiner::new(MinerConfig::default(), 1).snapshot());
    for format in forms() {
        let decoded = decode_state(&encode_state(&state, format), &StateLimits::default()).unwrap();
        assert_eq!(decoded, state);
    }
}

#[test]
fn the_two_forms_hold_the_same_state_and_binary_is_smaller() {
    let state = state_of(snapshot_of(&MinerConfig::default(), 3000));
    let json = encode_state(&state, StateFormat::Json);
    let binary = encode_state(&state, StateFormat::Binary);
    assert_eq!(
        decode_state(&json, &StateLimits::default()).unwrap(),
        decode_state(&binary, &StateLimits::default()).unwrap()
    );
    assert!(binary.len() < json.len(), "{} against {}", binary.len(), json.len());
}

#[test]
fn the_same_state_is_the_same_bytes() {
    for format in forms() {
        assert_eq!(encode_state(&small(), format), encode_state(&small(), format));
    }
}

#[test]
fn tokens_with_awkward_bytes_survive() {
    let mut miner = DrainMiner::new(MinerConfig::default(), 1);
    let awkward: [&[u8]; 6] = [
        b"quote\"back\\slash tab-free end",
        "snowman \u{2603} star \u{1f4a5} mix".as_bytes(),
        b"</script> <!-- ]]> end",
        b"ctl\x01\x02\x1f end",
        b"not \xff\xfe utf8 \x80 end",
        b"\xc3\x28 half sequence end",
    ];
    for (index, line) in awkward.iter().enumerate() {
        feed(&mut miner, line, index as i64);
    }
    let state = state_of(miner.snapshot());
    for format in forms() {
        let decoded = decode_state(&encode_state(&state, format), &StateLimits::default()).unwrap();
        assert_eq!(decoded, state, "{format:?}");
    }
}

#[test]
fn files_round_trip_with_and_without_gzip() {
    let directory = tempfile::tempdir().unwrap();
    for format in forms() {
        for name in ["state.bin", "state.json", "state.json.gz", "state.lfstate.gz"] {
            let path = directory.path().join(format!("{format:?}-{name}"));
            write_state_file(&path, &small(), format).unwrap();
            assert!(!directory.path().join(format!("{format:?}-{name}.part")).exists(), "the staging file is gone");
            assert_eq!(read_state_file(&path, &StateLimits::default()).unwrap(), small(), "{path:?}");
        }
    }
    let gz = std::fs::read(directory.path().join("Json-state.json.gz")).unwrap();
    assert_eq!(&gz[..2], &[0x1f, 0x8b], "a path that ends in .gz is compressed");
}

#[test]
fn something_that_is_not_a_state_is_refused() {
    let limits = StateLimits::default();
    for bytes in [&b""[..], b"hello", b"[1,2,3]", b"{\"kind\":\"other\"}", &[0u8; 64], b"LFSTATE"] {
        assert!(decode_state(bytes, &limits).is_err(), "{bytes:?}");
    }
    assert!(matches!(decode_state(b"hello", &limits), Err(StateError::NotState)));
}

#[test]
fn every_truncation_is_refused() {
    for format in forms() {
        let bytes = encode_state(&small(), format);
        let step = (bytes.len() / 600).max(1);
        for cut in (0..bytes.len()).step_by(step) {
            assert!(decode_state(&bytes[..cut], &StateLimits::default()).is_err(), "{format:?} cut at {cut}");
        }
        assert!(decode_state(&bytes[..bytes.len() - 1], &StateLimits::default()).is_err());
    }
}

#[test]
fn a_flipped_bit_is_refused_by_the_checksum() {
    for format in forms() {
        let bytes = encode_state(&small(), format);
        let step = (bytes.len() / 500).max(1);
        for at in (0..bytes.len()).step_by(step) {
            let mut damaged = bytes.clone();
            damaged[at] ^= 0x04;
            assert!(decode_state(&damaged, &StateLimits::default()).is_err(), "{format:?} byte {at}");
        }
    }
    let mut damaged = encode_state(&small(), StateFormat::Binary);
    let middle = damaged.len() / 2;
    damaged[middle] ^= 1;
    assert!(matches!(decode_state(&damaged, &StateLimits::default()), Err(StateError::Checksum)));
}

#[test]
fn a_newer_schema_is_refused_with_its_version() {
    let json = resigned(
        replaced(&encode_state(&small(), StateFormat::Json), "\"schema_version\":1", "\"schema_version\":2"),
        StateFormat::Json,
    );
    assert!(matches!(
        decode_state(&json, &StateLimits::default()),
        Err(StateError::Version { found: 2, supported: 1 })
    ));
    let mut binary = encode_state(&small(), StateFormat::Binary);
    binary[8] = 2;
    let binary = resigned(binary, StateFormat::Binary);
    assert!(matches!(
        decode_state(&binary, &StateLimits::default()),
        Err(StateError::Version { found: 2, supported: 1 })
    ));
}

#[test]
fn limits_are_checked_in_both_forms() {
    let state = small();
    let counts = state.snapshot.clusters.len() as u64;
    let tight = |change: fn(&mut StateLimits)| {
        let mut limits = StateLimits::default();
        change(&mut limits);
        limits
    };
    let cases: [(&str, StateLimits); 5] = [
        ("file", tight(|l| l.max_file_bytes = 200)),
        ("templates", tight(|l| l.max_clusters = 3)),
        ("nodes", tight(|l| l.max_nodes = 3)),
        ("token", tight(|l| l.max_token_bytes = 2)),
        ("total", tight(|l| l.max_total_token_bytes = 100)),
    ];
    assert!(counts > 3);
    for format in forms() {
        let bytes = encode_state(&state, format);
        for (name, limits) in &cases {
            assert!(matches!(decode_state(&bytes, limits), Err(StateError::Limit(_))), "{format:?} {name}");
        }
    }
}

#[test]
fn a_header_that_lies_about_its_counts_is_refused() {
    let json = encode_state(&small(), StateFormat::Json);
    let clusters = small().snapshot.clusters.len();
    let huge =
        resigned(replaced(&json, &format!("\"clusters\":{clusters}"), "\"clusters\":900000000000"), StateFormat::Json);
    assert!(matches!(decode_state(&huge, &StateLimits::default()), Err(StateError::Limit(_))));
    let fewer = resigned(
        replaced(&json, &format!("\"clusters\":{clusters}"), &format!("\"clusters\":{}", clusters - 1)),
        StateFormat::Json,
    );
    assert!(matches!(decode_state(&fewer, &StateLimits::default()), Err(StateError::Damaged(_))));
    let unknown = resigned(replaced(&json, "\"kind\":", "\"extra\":1,\"kind\":"), StateFormat::Json);
    assert!(matches!(decode_state(&unknown, &StateLimits::default()), Err(StateError::Damaged(_))));
}

#[test]
fn a_body_longer_than_its_limit_stops_early() {
    let state = small();
    let bytes = encode_state(&state, StateFormat::Json);
    let limits = StateLimits { max_nodes: state.snapshot.nodes.len() as u64 / 2, ..StateLimits::default() };
    let declared = replaced(
        &bytes,
        &format!("\"nodes\":{}", state.snapshot.nodes.len()),
        &format!("\"nodes\":{}", limits.max_nodes),
    );
    let declared = resigned(declared, StateFormat::Json);
    assert!(matches!(decode_state(&declared, &limits), Err(StateError::Limit(_))));
}

#[test]
fn a_compression_bomb_is_stopped_by_the_size_limit() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("bomb.json.gz");
    let mut encoder = flate2::write::GzEncoder::new(Vec::new(), flate2::Compression::best());
    let zeros = vec![b' '; 1 << 20];
    for _ in 0..64 {
        encoder.write_all(&zeros).unwrap();
    }
    std::fs::write(&path, encoder.finish().unwrap()).unwrap();
    let limits = StateLimits { max_file_bytes: 1 << 20, ..StateLimits::default() };
    assert!(matches!(read_state_file(&path, &limits), Err(StateError::Limit(_))));
}

#[test]
fn mutated_files_never_panic_and_never_build_a_broken_miner() {
    let mut random = 12345u64;
    for format in forms() {
        let original = encode_state(&small(), format);
        let body_end = match format {
            StateFormat::Binary => original.len() - 32,
            StateFormat::Json => original.iter().enumerate().filter(|(_, b)| **b == b'\n').nth(1).unwrap().0 + 1,
        };
        let mut refused = 0;
        for _ in 0..1500 {
            let mut bytes = original[..body_end].to_vec();
            for _ in 0..1 + next(&mut random) % 3 {
                let at = next(&mut random) as usize % bytes.len();
                match next(&mut random) % 3 {
                    0 => bytes[at] = next(&mut random) as u8,
                    1 => bytes[at] ^= 1 << (next(&mut random) % 8),
                    _ => {
                        bytes.remove(at);
                    }
                }
            }
            let mut signed = bytes.clone();
            signed.extend_from_slice(&original[body_end..]);
            let signed = resigned(signed, format);
            match decode_state(&signed, &StateLimits::default()) {
                Err(_) => refused += 1,
                Ok(state) => {
                    if DrainMiner::from_snapshot(state.snapshot, 1).is_err() {
                        refused += 1;
                    }
                }
            }
        }
        assert!(refused > 500, "{format:?}: most mutations must be refused ({refused})");
    }
}

#[test]
fn a_state_path_is_checked_before_a_run_and_leaves_nothing_behind() {
    let directory = tempfile::tempdir().unwrap();
    let good = directory.path().join("state.json");
    check_state_writable(&good).unwrap();
    assert_eq!(std::fs::read_dir(directory.path()).unwrap().count(), 0, "the staging file is removed");
    let missing = directory.path().join("no-such-folder").join("state.json");
    assert!(matches!(check_state_writable(&missing), Err(StateError::Write { .. })));
}

#[test]
fn a_newer_layout_is_reported_as_newer_whatever_else_changed() {
    let limits = StateLimits::default();
    let json = b"{\"kind\":\"logfold-state\",\"schema_version\":9,\"a_field_of_the_future\":1}
not the body of today
";
    assert!(matches!(decode_state(json, &limits), Err(StateError::Version { found: 9, supported: 1 })));
    let mut binary = BINARY_MAGIC.to_vec();
    binary.extend_from_slice(&[9, 0]);
    binary.extend_from_slice(b"a layout that has no checksum at the end");
    assert!(matches!(decode_state(&binary, &limits), Err(StateError::Version { found: 9, supported: 1 })));
}

#[test]
fn a_header_line_that_is_too_long_is_refused() {
    let mut bytes = b"{\"kind\":\"logfold-state\",\"x\":\"".to_vec();
    bytes.extend(std::iter::repeat_n(b'a', 70_000));
    bytes.extend_from_slice(
        b"\"}
",
    );
    assert!(matches!(decode_state(&bytes, &StateLimits::default()), Err(StateError::Damaged(_))));
}

#[test]
fn a_gzip_file_is_found_by_its_content_not_by_its_name() {
    let directory = tempfile::tempdir().unwrap();
    let named = directory.path().join("state.json.gz");
    write_state_file(&named, &small(), StateFormat::Json).unwrap();
    let renamed = directory.path().join("model.bin");
    std::fs::rename(&named, &renamed).unwrap();
    assert_eq!(read_state_file(&renamed, &StateLimits::default()).unwrap(), small());
    let compressed = std::fs::read(&renamed).unwrap();
    let mut inside = Vec::new();
    std::io::Read::read_to_end(&mut flate2::read::GzDecoder::new(compressed.as_slice()), &mut inside).unwrap();
    assert_eq!(inside, encode_state(&small(), StateFormat::Json), "the bytes before compression are the plain file");
}

#[test]
fn a_leftover_staging_file_is_replaced_and_never_written_through() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("state.json");
    let staging = directory.path().join(format!("state.json.{}.part", std::process::id()));
    std::fs::write(&staging, b"left by a crashed process").unwrap();
    write_state_file(&path, &small(), StateFormat::Json).unwrap();
    assert!(!staging.exists());
    assert_eq!(read_state_file(&path, &StateLimits::default()).unwrap(), small());
}

#[cfg(unix)]
#[test]
fn a_link_in_the_place_of_the_staging_file_is_not_written_through() {
    let directory = tempfile::tempdir().unwrap();
    let victim = directory.path().join("victim.txt");
    std::fs::write(&victim, b"must stay as it is").unwrap();
    let path = directory.path().join("state.json");
    let staging = directory.path().join(format!("state.json.{}.part", std::process::id()));
    std::os::unix::fs::symlink(&victim, &staging).unwrap();
    write_state_file(&path, &small(), StateFormat::Json).unwrap();
    assert_eq!(std::fs::read(&victim).unwrap(), b"must stay as it is");
    assert_eq!(read_state_file(&path, &StateLimits::default()).unwrap(), small());
}

/// A valid snapshot of `clusters` templates of six tokens in 100 leaves, built directly (no mining).
fn synthetic(clusters: usize) -> MinerSnapshot {
    const WORDS: usize = 100;
    let word = |i: usize| format!("{}{}", (b'a' + (i / 26) as u8) as char, (b'a' + (i % 26) as u8) as char);
    let mut nodes = vec![NodeSnapshot { children: Vec::new(), clusters: Vec::new() }];
    let mut keys: Vec<Box<[u8]>> = (0..WORDS).map(|i| Box::from(word(i).as_bytes())).collect();
    keys.sort();
    for (index, key) in keys.iter().enumerate() {
        nodes[0].children.push((key.clone(), index as u32 + 1));
        nodes.push(NodeSnapshot { children: Vec::new(), clusters: Vec::new() });
    }
    let mut templates = Vec::with_capacity(clusters);
    for id in 0..clusters {
        let leaf = id % WORDS;
        let mut tokens: Vec<Box<[u8]>> = vec![keys[leaf].clone()];
        for position in 1..6 {
            tokens.push(Box::from(format!("t{}x{}", position, id % (31 + position)).as_bytes()));
        }
        nodes[leaf + 1].clusters.push(id as u32);
        let history = History {
            count: id as u64 % 1000 + 1,
            first: 1_700_000_000_000_000 + id as i64,
            last: 1_700_000_100_000_000 + id as i64,
            levels: [0, 1, id as u64 % 50, 0, 0, 0],
        };
        templates.push(ClusterSnapshot { tokens, history });
    }
    MinerSnapshot {
        depth: 4,
        threshold_micro: 400_000,
        max_children: 128,
        max_templates: 2_000_000,
        nodes,
        roots: vec![(6, 0)],
        clusters: templates,
        overflow: Vec::new(),
    }
}

/// Times both forms on 10^4, 10^5 and 10^6 templates: `cargo test --release -p logfold-tests --test io_state -- --ignored --nocapture`.
#[test]
#[ignore = "a measurement, not a test"]
fn measure_state_files() {
    use std::time::Instant;
    println!("| templates | form | bytes | bytes per template | write | read | rebuild the miner |");
    println!("|---:|---|---:|---:|---:|---:|---:|");
    for clusters in [10_000, 100_000, 1_000_000] {
        let state = state_of(synthetic(clusters));
        let limits = StateLimits::default();
        for format in forms() {
            let started = Instant::now();
            let bytes = encode_state(&state, format);
            let write = started.elapsed();
            let started = Instant::now();
            let decoded = decode_state(&bytes, &limits).unwrap();
            let read = started.elapsed();
            let started = Instant::now();
            let miner = DrainMiner::from_snapshot(decoded.snapshot, 1).unwrap();
            let rebuild = started.elapsed();
            assert_eq!(miner.cluster_count(), clusters);
            println!(
                "| {clusters} | {format:?} | {} | {} | {:.0} ms | {:.0} ms | {:.0} ms |",
                bytes.len(),
                bytes.len() / clusters,
                write.as_secs_f64() * 1e3,
                read.as_secs_f64() * 1e3,
                rebuild.as_secs_f64() * 1e3
            );
        }
    }
}
