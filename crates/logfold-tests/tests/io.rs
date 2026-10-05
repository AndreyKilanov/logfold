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
