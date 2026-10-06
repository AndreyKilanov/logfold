#![allow(missing_docs)]

mod format {
    use logfold_core::Level;
    use logfold_io::*;

    fn json_format() -> CompiledFormat {
        CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Json {
                message_keys: vec!["message".into(), "msg".into()],
                time_keys: vec!["ts".into()],
                level_keys: vec!["level".into()],
            },
            ts_format: None,
            multiline: false,
        })
        .unwrap()
    }

    #[test]
    fn json_extracts_fields() {
        let fmt = json_format();
        let line = br#"{"level":"warning","msg":"disk 90%","ts":"1970-01-01T00:00:02Z"}"#;
        let rec = fmt.parse(line, line.len()).unwrap();
        assert_eq!(&*rec.message, b"disk 90%");
        assert_eq!(rec.timestamp, Some(2_000_000));
        assert_eq!(rec.level, Some(Level::Warn));
        assert!(fmt.parse(b"not json", 8).is_none());
        assert!(fmt.parse(br#"{"other":1}"#, 11).is_none());
    }

    #[test]
    fn regex_groups_and_continuation() {
        let fmt = CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Regex {
                pattern: r"^(?P<ts>\S+) (?P<lvl>[A-Z]+) (?P<msg>.*)$".into(),
                message_group: Some("msg".into()),
                time_group: Some("ts".into()),
                level_group: Some("lvl".into()),
            },
            ts_format: None,
            multiline: true,
        })
        .unwrap();
        let text = b"1970-01-01T00:00:01Z ERROR boom\n  at frame 1";
        let first = "1970-01-01T00:00:01Z ERROR boom".len();
        let rec = fmt.parse(text, first).unwrap();
        assert_eq!(&*rec.message, b"boom\n  at frame 1");
        assert_eq!(rec.level, Some(Level::Error));
        assert_eq!(rec.timestamp, Some(1_000_000));
        assert!(fmt.starts_record(b"1970-01-01T00:00:01Z INFO ok"));
        assert!(!fmt.starts_record(b"  at frame 1"));
    }

    #[test]
    fn rejects_unknown_group() {
        let result = CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Regex {
                pattern: "(?P<a>x)".into(),
                message_group: Some("nope".into()),
                time_group: None,
                level_group: None,
            },
            ts_format: None,
            multiline: false,
        });
        assert!(result.is_err());
    }
}

mod lines {
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
}

mod records {
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
                let window = ScanWindow {
                    skip_first_line: start > 0,
                    skip_leading_continuations: start > 0,
                    end,
                    time: TimeWindow::default(),
                };
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
}

mod time_window {
    use logfold_io::*;

    const SECOND: i64 = 1_000_000;

    fn timed() -> CompiledFormat {
        CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Regex {
                pattern: r"^(?P<ts>\S+) (?P<msg>.*)$".into(),
                message_group: Some("msg".into()),
                time_group: Some("ts".into()),
                level_group: None,
            },
            ts_format: None,
            multiline: false,
        })
        .unwrap()
    }

    fn run(data: &[u8], time: TimeWindow) -> (Vec<String>, Counters) {
        let mut messages = Vec::new();
        let window = ScanWindow { time, ..ScanWindow::whole() };
        let (counters, _) = scan_records(
            LineReader::new(data, 0),
            &timed(),
            window,
            |rec| messages.push(String::from_utf8_lossy(&rec.message).into_owned()),
            |_| true,
        )
        .unwrap();
        (messages, counters)
    }

    #[test]
    fn the_window_is_half_open() {
        let window = TimeWindow { since: Some(10), until: Some(20) };
        assert_eq!(window.place(Some(9)), Placement::Outside);
        assert_eq!(window.place(Some(10)), Placement::Inside);
        assert_eq!(window.place(Some(19)), Placement::Inside);
        assert_eq!(window.place(Some(20)), Placement::Outside);
    }

    #[test]
    fn one_bound_leaves_the_other_side_open() {
        let from = TimeWindow { since: Some(10), until: None };
        assert_eq!((from.place(Some(9)), from.place(Some(i64::MAX))), (Placement::Outside, Placement::Inside));
        let to = TimeWindow { since: None, until: Some(10) };
        assert_eq!((to.place(Some(i64::MIN)), to.place(Some(10))), (Placement::Inside, Placement::Outside));
    }

    #[test]
    fn an_open_window_admits_everything_even_without_a_time() {
        let open = TimeWindow::default();
        assert!(open.is_open());
        assert_eq!(open.place(None), Placement::Inside);
        assert_eq!(open.place(Some(-5)), Placement::Inside);
    }

    #[test]
    fn a_bounded_window_cannot_place_a_record_without_a_time() {
        let bounded = TimeWindow { since: Some(0), until: None };
        assert_eq!(bounded.place(None), Placement::Untimed);
    }

    #[test]
    fn records_outside_are_counted_apart_and_not_emitted() {
        let data = b"1970-01-01T00:00:01Z a\n1970-01-01T00:00:05Z b\nnot-a-time c\n1970-01-01T00:00:09Z d\n";
        let (all, counters) = run(data, TimeWindow::default());
        assert_eq!(all, vec!["a", "b", "c", "d"]);
        assert_eq!((counters.records, counters.out_of_range, counters.untimed), (4, 0, 0));
        let (inside, counters) = run(data, TimeWindow { since: Some(2 * SECOND), until: Some(9 * SECOND) });
        assert_eq!(inside, vec!["b"]);
        assert_eq!((counters.lines, counters.records, counters.out_of_range, counters.untimed), (4, 1, 2, 1));
    }

    #[test]
    fn the_counters_add_up_over_chunks() {
        let mut total = Counters::default();
        total.add(&Counters { records: 2, out_of_range: 3, untimed: 1, ..Counters::default() });
        total.add(&Counters { records: 1, out_of_range: 4, untimed: 2, ..Counters::default() });
        assert_eq!((total.records, total.out_of_range, total.untimed), (3, 7, 3));
    }
}

mod timestamp {
    use logfold_io::*;

    #[test]
    fn iso_variants() {
        assert_eq!(parse_iso(b"1970-01-01T00:00:01Z"), Some((1_000_000, true)));
        assert_eq!(parse_iso(b"1970-01-01 00:00:01"), Some((1_000_000, false)));
        assert_eq!(parse_iso(b"1970-01-01 03:00:00+03:00"), Some((0, true)));
        assert_eq!(parse_iso(b"2026-10-04T12:00:00.123456789Z"), Some((1_791_115_200_123_456, true)));
        assert_eq!(parse_iso(b"1970-01-02"), Some((86_400_000_000, false)));
        assert_eq!(parse_iso(b"2026-13-01"), None);
        assert_eq!(parse_iso(b"2026-10-04T12:00:00 garbage"), None);
    }

    #[test]
    fn strptime_nginx_and_syslog() {
        let nginx = TsFormat::new("%d/%b/%Y:%H:%M:%S %z").unwrap();
        assert_eq!(nginx.parse(b"04/Oct/2026:12:00:00 +0300"), Some((1_791_104_400_000_000, true)));
        let syslog = TsFormat::new("%b %e %H:%M:%S").unwrap();
        assert_eq!(syslog.parse(b"Jan  2 00:00:01"), Some((86_400_000_000 + 1_000_000, false)));
        assert!(TsFormat::new("%Q").is_err());
    }

    #[test]
    fn epoch_scales() {
        assert_eq!(epoch_int_to_micros(1_700_000_000), Some(1_700_000_000_000_000));
        assert_eq!(epoch_int_to_micros(1_700_000_000_000), Some(1_700_000_000_000_000));
        assert_eq!(epoch_float_to_micros(1.5), Some(1_500_000));
    }
}

mod limits {
    use logfold_io::*;

    fn collect(data: &[u8]) -> Vec<(Vec<u8>, u64)> {
        let mut reader = LineReader::new(data, 0);
        let mut out = Vec::new();
        while let Some(line) = reader.next_line().unwrap() {
            out.push((line.bytes.to_vec(), line.start));
        }
        out
    }

    fn lengths(data: &[u8]) -> Vec<(usize, u64)> {
        collect(data).iter().map(|(bytes, start)| (bytes.len(), *start)).collect()
    }

    #[test]
    fn a_long_line_keeps_its_first_bytes_and_the_next_line_starts_where_it_should() {
        let mut data = b"ab\n".to_vec();
        data.extend(std::iter::repeat_n(b'x', MAX_LINE_BYTES + 5));
        data.extend_from_slice(b"\ntail\nend");
        let lines = collect(&data);
        assert_eq!(lines.len(), 4);
        assert_eq!(lines[0], (b"ab".to_vec(), 0));
        assert_eq!((lines[1].0.len(), lines[1].1), (MAX_LINE_BYTES, 3));
        assert!(lines[1].0.iter().all(|byte| *byte == b'x'));
        assert_eq!(lines[2], (b"tail".to_vec(), 3 + MAX_LINE_BYTES as u64 + 5 + 1));
        assert_eq!(lines[3].0, b"end".to_vec());
    }

    #[test]
    fn the_limit_is_on_the_content_of_the_line() {
        for (raw, kept) in [
            (MAX_LINE_BYTES - 1, MAX_LINE_BYTES - 1),
            (MAX_LINE_BYTES, MAX_LINE_BYTES),
            (MAX_LINE_BYTES + 1, MAX_LINE_BYTES),
            (MAX_LINE_BYTES + 2, MAX_LINE_BYTES),
        ] {
            let mut data = vec![b'y'; raw];
            data.extend_from_slice(b"\nnext\n");
            assert_eq!(lengths(&data), vec![(kept, 0), (4, raw as u64 + 1)], "raw length {raw}");
        }
    }

    #[test]
    fn a_carriage_return_is_removed_only_at_the_end_of_the_line() {
        for (raw, kept) in [
            (MAX_LINE_BYTES - 1, MAX_LINE_BYTES - 2),
            (MAX_LINE_BYTES, MAX_LINE_BYTES - 1),
            (MAX_LINE_BYTES + 1, MAX_LINE_BYTES),
            (MAX_LINE_BYTES + 2, MAX_LINE_BYTES),
        ] {
            let mut data = vec![b'y'; raw];
            data[raw - 1] = b'\r';
            data.extend_from_slice(b"\nnext\n");
            assert_eq!(lengths(&data), vec![(kept, 0), (4, raw as u64 + 1)], "raw length {raw}");
        }
    }

    #[test]
    fn a_long_line_without_a_line_feed_ends_the_stream() {
        let data = vec![b'z'; 2 * MAX_LINE_BYTES + 7];
        assert_eq!(lengths(&data), vec![(MAX_LINE_BYTES, 0)]);
        assert!(collect(&data[..0]).is_empty());
    }

    fn plain() -> CompiledFormat {
        CompiledFormat::new(&FormatConfig {
            spec: FormatSpec::Plain { record_start: Some(r"^\d{4}-".to_string()) },
            ts_format: None,
            multiline: true,
        })
        .unwrap()
    }

    fn run(data: &[u8]) -> (Vec<usize>, Counters) {
        let mut sizes = Vec::new();
        let (counters, _) = scan_records(
            LineReader::new(data, 0),
            &plain(),
            ScanWindow::whole(),
            |rec| sizes.push(rec.message.len()),
            |_| true,
        )
        .unwrap();
        (sizes, counters)
    }

    #[test]
    fn a_record_stops_taking_lines_at_the_limit_and_the_lines_are_still_counted() {
        let line = "x".repeat(99);
        let count = 3 * MAX_RECORD_BYTES / 100;
        let mut data = String::from("2026-01 first\n");
        for _ in 0..count {
            data.push_str(&line);
            data.push('\n');
        }
        data.push_str("2026-02 second\n");
        let (sizes, counters) = run(data.as_bytes());
        assert_eq!(sizes.len(), 2);
        assert!(sizes[0] >= MAX_RECORD_BYTES && sizes[0] < MAX_RECORD_BYTES + 200, "{}", sizes[0]);
        assert_eq!(sizes[1], "2026-02 second".len());
        assert_eq!((counters.lines, counters.records, counters.unparsed), (count as u64 + 2, 2, 0));
    }

    #[test]
    fn a_record_below_the_limit_is_unchanged() {
        let (sizes, counters) = run(b"2026-01 a\n  b\n  c\n2026-02 d\n");
        assert_eq!(sizes, vec!["2026-01 a\n  b\n  c".len(), "2026-02 d".len()]);
        assert_eq!(counters.lines, 4);
    }
}
