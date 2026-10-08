#![no_main]

//! A JSON state file with a valid checksum around fuzzed header and body lines, so that the fuzzer reaches the parser
//! instead of stopping at the checksum. Neither a panic nor an unbounded allocation is allowed.

use libfuzzer_sys::fuzz_target;
use logfold_core::DrainMiner;
use logfold_io::{StateFormat, StateLimits, decode_state, encode_state};
use sha2::{Digest, Sha256};

const LIMITS: StateLimits = StateLimits {
    max_file_bytes: 1 << 20,
    max_clusters: 2_000,
    max_nodes: 8_000,
    max_token_bytes: 4_096,
    max_total_token_bytes: 1 << 20,
};

fuzz_target!(|data: &[u8]| {
    let split = data.iter().position(|&byte| byte == b'\n').unwrap_or(data.len());
    let (header, body) = data.split_at(split);
    let body: Vec<u8> = body.iter().skip(1).map(|&byte| if byte == b'\n' { b' ' } else { byte }).collect();
    let mut signed = Vec::with_capacity(data.len() + 2);
    signed.extend_from_slice(header);
    signed.push(b'\n');
    signed.extend_from_slice(&body);
    signed.push(b'\n');
    let digest = Sha256::digest(&signed);
    let hex: String = digest.iter().map(|byte| format!("{byte:02x}")).collect();
    let mut file = signed;
    file.extend_from_slice(format!("{{\"sha256\":\"{hex}\"}}\n").as_bytes());

    if let Ok(state) = decode_state(&file, &LIMITS) {
        let again = encode_state(&state, StateFormat::Json);
        assert!(decode_state(&again, &LIMITS).is_ok(), "a decoded state must encode into a readable file");
        let _ = DrainMiner::from_snapshot(state.snapshot, 1);
    }
});
