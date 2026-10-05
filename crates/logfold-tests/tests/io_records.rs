#![allow(missing_docs)]

use logfold_io::*;

fn plain(multiline: bool) -> CompiledFormat {
    CompiledFormat::new(&FormatConfig {
        spec: FormatSpec::Plain { record_start: multiline.then(|| r"^\d{4}-".to_string()) },
        ts_format: None,
        multiline,
    })
    .unwrap()
}

fn run(data: &[u8], format: &CompiledFormat, window: ScanWindow, offset: u64) -> (Vec<String>, Counters) {
    let mut messages = Vec::new();
    let (counters, _) = scan_records(
        LineReader::new(data, offset),
        format,
        window,
        |rec| messages.push(String::from_utf8_lossy(&rec.message).into_owned()),
        |_| true,
    )
    .unwrap();
    (messages, counters)
}

#[test]
fn single_line_records_skip_blank_lines() {
    let (messages, counters) = run(b"a\n\nb\r\nc", &plain(false), ScanWindow::whole(), 0);
    assert_eq!(messages, vec!["a", "b", "c"]);
    assert_eq!((counters.lines, counters.records, counters.unparsed), (4, 3, 0));
}

#[test]
fn multiline_joins_continuations_and_counts_leading_garbage() {
    let data = b"junk\n2026-01 first\n  cont\n2026-02 second\n";
    let (messages, counters) = run(data, &plain(true), ScanWindow::whole(), 0);
    assert_eq!(messages, vec!["2026-01 first\n  cont", "2026-02 second"]);
    assert_eq!((counters.lines, counters.records, counters.unparsed), (4, 2, 1));
}

#[test]
fn chunks_partition_records_exactly() {
    let data = b"junk\n\n2026-01 a\n  x\n\n2026-02 b\n2026-03 c\n  y\n\n  z\n2026-04 d\n\n";
    let format = plain(true);
    let mut all = Vec::new();
    let mut total = Counters::default();
    for split in 1..data.len() {
        all.clear();
        total = Counters::default();
        let bounds = [(0u64, split as u64), (split as u64, u64::MAX)];
        for (start, end) in bounds {
            let begin = start.saturating_sub(1);
            let window = ScanWindow { skip_first_line: start > 0, skip_leading_continuations: start > 0, end };
            let (messages, counters) = run(&data[begin as usize..], &format, window, begin);
            all.extend(messages);
            total.add(&counters);
        }
        assert_eq!(all, vec!["2026-01 a\n  x", "2026-02 b", "2026-03 c\n  y\n  z", "2026-04 d"], "split {split}");
        assert_eq!((total.lines, total.records, total.unparsed), (12, 4, 1), "split {split}");
    }
    assert_eq!(all.len(), 4);
    assert_eq!(total.records, 4);
}
