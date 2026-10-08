#![no_main]

//! A gzip source with fuzzed content after the magic bytes: it is opened the way `analyze` opens it and read line by
//! line. The decompressed output is cut at a fixed size so that a compression bomb cannot stall a run. Neither a panic
//! nor an unbounded allocation is allowed.

use std::io::{Read, Write};

use libfuzzer_sys::fuzz_target;
use logfold_io::{LineReader, inspect, open_source};

const MAX_DECOMPRESSED_BYTES: u64 = 8 << 20;
const MAX_LINES: usize = 200_000;

fuzz_target!(|data: &[u8]| {
    let Ok(dir) = tempfile::tempdir() else { return };
    let path = dir.path().join("fuzz.log.gz");
    let Ok(mut file) = std::fs::File::create(&path) else { return };
    if file.write_all(&[0x1f, 0x8b]).and_then(|()| file.write_all(data)).is_err() {
        return;
    }
    drop(file);

    let Ok(info) = inspect(&path) else { return };
    let Ok(source) = open_source(&path, &info, 0) else { return };
    let mut lines = LineReader::new(source.take(MAX_DECOMPRESSED_BYTES), 0);
    for _ in 0..MAX_LINES {
        match lines.next_line() {
            Ok(Some(_)) => {}
            Ok(None) | Err(_) => break,
        }
    }
});
