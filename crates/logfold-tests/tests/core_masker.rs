#![allow(missing_docs)]

use logfold_core::*;

fn masked_with(rules: &[MaskRule], text: &str) -> String {
    let masker = RuleMasker::new(rules).unwrap();
    let mut scratch = MaskScratch::default();
    String::from_utf8(masker.mask(text.as_bytes(), &mut scratch).to_vec()).unwrap()
}

fn masked(text: &str) -> String {
    masked_with(&default_mask_rules(), text)
}

#[test]
fn masks_common_values() {
    assert_eq!(masked("conn from 10.0.0.1:8080 took 12.5 ms"), "conn from <IP> took <NUM> ms");
    assert_eq!(masked("id 123e4567-e89b-12d3-a456-426614174000 ok"), "id <UUID> ok");
    assert_eq!(masked("at 2026-10-04 12:00:01.123Z done"), "at <TS> done");
    assert_eq!(masked("open /var/log/app.log"), "open <PATH>");
    assert_eq!(masked("ptr 0xdeadBEEF"), "ptr <HEX>");
}

#[test]
fn leaves_embedded_digits() {
    assert_eq!(masked("user42 failed"), "user42 failed");
}

#[test]
fn earliest_rule_wins_at_the_same_position() {
    let rules = vec![
        MaskRule { name: "a".into(), pattern: "ab".into(), token: "<A>".into(), ascii: true },
        MaskRule { name: "b".into(), pattern: "abc".into(), token: "<B>".into(), ascii: true },
    ];
    assert_eq!(masked_with(&rules, "xabcx"), "x<A>cx");
}

#[test]
fn leftmost_match_wins_over_rule_order() {
    let rules = vec![
        MaskRule { name: "late".into(), pattern: "cd".into(), token: "<L>".into(), ascii: true },
        MaskRule { name: "early".into(), pattern: "bc".into(), token: "<E>".into(), ascii: true },
    ];
    assert_eq!(masked_with(&rules, "abcd"), "a<E>d");
}

#[test]
fn hand_written_default_masker_matches_the_regex_masker() {
    let fast = RuleMasker::new(&default_mask_rules()).unwrap();
    assert!(fast.uses_default_scanner());
    let slow = RuleMasker::with_regex(&default_mask_rules()).unwrap();
    let alphabet: Vec<&[u8]> = vec![
        b"0",
        b"1",
        b"2",
        b"7",
        b"9",
        b"a",
        b"f",
        b"A",
        b"F",
        b"g",
        b"x",
        b"X",
        b"0x",
        b".",
        b".",
        b":",
        b"-",
        b"-",
        b"/",
        b"/",
        b"_",
        b" ",
        b" ",
        b"+",
        b",",
        b"T",
        b"Z",
        b"e",
        b"123",
        b"2026-10-04",
        b"12:00:01",
        b"10.0.0.1",
        b"::",
        b"abcdef12-1234-1234-1234-123456789abc",
        b"x2026-10-04 12:00:01",
        b"blk_-123",
        b"job_2008",
        b"A1b2c3d4-",
        b"1234-",
        b"deadbeef-dead-beef-dead-beefdeadbeef",
        b"zz",
        b"20260-1",
        b"1.2.3.4.5",
        b"v1.2.3",
        b"0x",
    ];
    let mut state: u64 = 0x9E37_79B9_7F4A_7C15;
    let mut next = || {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state
    };
    let (mut a, mut b) = (MaskScratch::default(), MaskScratch::default());
    for round in 0..400_000 {
        let pieces = (next() % 14) as usize;
        let mut text = Vec::new();
        for _ in 0..pieces {
            text.extend_from_slice(alphabet[(next() % alphabet.len() as u64) as usize]);
        }
        let expected = slow.mask(&text, &mut a).to_vec();
        let actual = fast.mask(&text, &mut b).to_vec();
        assert_eq!(
            String::from_utf8_lossy(&actual),
            String::from_utf8_lossy(&expected),
            "round {round}, input {:?}",
            String::from_utf8_lossy(&text)
        );
    }
}

#[test]
fn no_rules_leave_the_input_untouched() {
    assert_eq!(masked_with(&[], "keep 12"), "keep 12");
}

#[test]
fn rejects_empty_matching_pattern() {
    let rule = MaskRule { name: "bad".into(), pattern: "a*".into(), token: "<A>".into(), ascii: true };
    assert!(RuleMasker::new(&[rule]).is_err());
}
