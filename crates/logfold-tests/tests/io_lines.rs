#![allow(missing_docs)]

use logfold_io::*;

fn collect(data: &[u8]) -> Vec<(Vec<u8>, u64)> {
    let mut reader = LineReader::new(data, 0);
    let mut out = Vec::new();
    while let Some(line) = reader.next_line().unwrap() {
        out.push((line.bytes.to_vec(), line.start));
    }
    out
}

#[test]
fn splits_lines_and_tracks_offsets() {
    let lines = collect(b"ab\r\ncd\n\nlast");
    assert_eq!(lines, vec![(b"ab".to_vec(), 0), (b"cd".to_vec(), 4), (Vec::new(), 7), (b"last".to_vec(), 8)]);
}

#[test]
fn handles_lines_longer_than_window() {
    let mut data = vec![b'x'; INITIAL_WINDOW + 10];
    data.push(b'\n');
    data.extend_from_slice(b"tail\n");
    let lines = collect(&data);
    assert_eq!(lines.len(), 2);
    assert_eq!(lines[0].0.len(), INITIAL_WINDOW + 10);
    assert_eq!(lines[1].0, b"tail".to_vec());
}

#[test]
fn empty_stream_has_no_lines() {
    assert!(collect(b"").is_empty());
}
