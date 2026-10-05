#![allow(missing_docs)]

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
