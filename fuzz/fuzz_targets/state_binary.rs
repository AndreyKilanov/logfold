#![no_main]

//! A binary state file with a valid magic and checksum around fuzzed content, so that the fuzzer reaches the parser
//! instead of stopping at the checksum. Neither a panic nor an unbounded allocation is allowed.

use libfuzzer_sys::fuzz_target;
use logfold_core::DrainMiner;
use logfold_io::{BINARY_MAGIC, StateFormat, StateLimits, decode_state, encode_state};
use sha2::{Digest, Sha256};

const LIMITS: StateLimits = StateLimits {
    max_file_bytes: 1 << 20,
    max_clusters: 2_000,
    max_nodes: 8_000,
    max_token_bytes: 4_096,
    max_total_token_bytes: 1 << 20,
};

fuzz_target!(|data: &[u8]| {
    let mut file = Vec::with_capacity(BINARY_MAGIC.len() + data.len() + 32);
    file.extend_from_slice(BINARY_MAGIC);
    file.extend_from_slice(data);
    let digest = Sha256::digest(&file);
    file.extend_from_slice(&digest);

    if let Ok(state) = decode_state(&file, &LIMITS) {
        let again = encode_state(&state, StateFormat::Binary);
        assert!(decode_state(&again, &LIMITS).is_ok(), "a decoded state must encode into a readable file");
        let _ = DrainMiner::from_snapshot(state.snapshot, 1);
    }
});
