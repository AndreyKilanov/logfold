#![allow(missing_docs)]
//! Layered masking and the checks of masking rules (`docs/ALGORITHM.md` §2).

use logfold_core::{
    MAX_MASK_RULES, MAX_PATTERN_BYTES, MaskCheck, MaskRule, MaskScratch, RuleMasker, default_mask_rules,
};
use proptest::prelude::*;

fn rule(name: &str, pattern: &str, token: &str, check: Option<MaskCheck>) -> MaskRule {
    MaskRule { name: name.into(), pattern: pattern.into(), token: token.into(), ascii: true, check }
}

fn card() -> MaskRule {
    rule("card", r"\b(?:\d{4}[ -]){3}\d{1,7}\b|\b\d{13,19}\b", "<CARD>", Some(MaskCheck::Luhn))
}

fn iban() -> MaskRule {
    rule("iban", r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b", "<IBAN>", Some(MaskCheck::Iban))
}

fn email() -> MaskRule {
    rule("email", r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", "<EMAIL>", None)
}

fn with_defaults(mut rules: Vec<MaskRule>) -> Vec<MaskRule> {
    rules.extend(default_mask_rules());
    rules
}

fn run(masker: &RuleMasker, text: &str) -> String {
    let mut scratch = MaskScratch::default();
    String::from_utf8(masker.mask(text.as_bytes(), &mut scratch).to_vec()).unwrap()
}

fn masked(rules: &[MaskRule], text: &str) -> String {
    run(&RuleMasker::new(rules).unwrap(), text)
}

#[test]
fn luhn_accepts_public_test_cards_and_rejects_the_rest() {
    for good in ["4111 1111 1111 1111", "5500-0000-0000-0004", "378282246310005", "6011111111111117"] {
        assert!(MaskCheck::Luhn.accepts(good.as_bytes()), "{good}");
    }
    for bad in ["4111 1111 1111 1112", "4111 1111 1111 111x", "000000000000", "00000000000000000000", "", "1234"] {
        assert!(!MaskCheck::Luhn.accepts(bad.as_bytes()), "{bad}");
    }
}

#[test]
fn iban_accepts_public_test_numbers_and_rejects_the_rest() {
    for good in [
        "GB82 WEST 1234 5698 7654 32",
        "DE89370400440532013000",
        "FR1420041010050500013M02606",
        "NL91 ABNA 0417 1643 00",
    ] {
        assert!(MaskCheck::Iban.accepts(good.as_bytes()), "{good}");
    }
    for bad in [
        "GB82 WEST 1234 5698 7654 33",
        "DE89370400440532013001",
        "1282WEST12345698765432",
        "GB82",
        "GB82WEST1234569876543!",
        "",
    ] {
        assert!(!MaskCheck::Iban.accepts(bad.as_bytes()), "{bad}");
    }
}

#[test]
fn names_round_trip() {
    for check in [MaskCheck::Luhn, MaskCheck::Iban] {
        assert_eq!(MaskCheck::from_name(check.name()), Some(check));
    }
    assert_eq!(MaskCheck::from_name("crc"), None);
}

#[test]
fn a_selected_rule_runs_before_the_default_rules() {
    let rules = with_defaults(vec![card()]);
    assert_eq!(masked(&rules, "card 4111 1111 1111 1111 ok 12"), "card <CARD> ok <NUM>");
}

#[test]
fn the_default_rules_alone_are_unchanged() {
    let rules = default_mask_rules();
    let masker = RuleMasker::new(&rules).unwrap();
    assert!(masker.uses_default_scanner());
    assert_eq!(run(&masker, "4111 1111 1111 1111 at 10.0.0.1"), "<NUM> <NUM> <NUM> <NUM> at <IP>");
}

#[test]
fn a_candidate_that_fails_its_check_is_left_to_the_default_rules() {
    let rules = with_defaults(vec![card()]);
    assert_eq!(masked(&rules, "pay 4111 1111 1111 1112 now"), "pay <NUM> <NUM> <NUM> <NUM> now");
}

#[test]
fn the_search_goes_on_after_a_rejected_candidate() {
    let rules = with_defaults(vec![card()]);
    assert_eq!(masked(&rules, "4111 1111 1111 1112 then 4111 1111 1111 1111"), "<NUM> <NUM> <NUM> <NUM> then <CARD>");
}

#[test]
fn a_rejected_candidate_hides_the_rules_after_it_at_the_same_position() {
    let greedy = rule("any", r"\d[\d ]{10,}\d", "<ANY>", None);
    let rules = vec![card(), greedy];
    assert_eq!(masked(&rules, "x 4111 1111 1111 1112 y"), "x 4111 1111 1111 1112 y");
}

#[test]
fn several_selected_rules_share_one_pass_in_list_order() {
    let rules = with_defaults(vec![email(), card(), iban()]);
    assert_eq!(
        masked(&rules, "mail bob@example.com iban GB82 WEST 1234 5698 7654 32 card 4111111111111111 id 7"),
        "mail <EMAIL> iban <IBAN> card <CARD> id <NUM>"
    );
}

#[test]
fn a_list_without_the_default_rules_is_one_layer() {
    let rules = vec![email(), card()];
    assert_eq!(masked(&rules, "bob@example.com 4111111111111111 12"), "<EMAIL> <CARD> 12");
    assert!(!RuleMasker::new(&rules).unwrap().uses_default_scanner());
}

#[test]
fn text_without_a_match_is_borrowed() {
    let rules = with_defaults(vec![email(), card()]);
    let masker = RuleMasker::new(&rules).unwrap();
    let mut scratch = MaskScratch::default();
    let input = b"plain words only";
    assert!(std::ptr::eq(masker.mask(input, &mut scratch), input.as_slice()));
}

#[test]
fn a_token_that_the_default_rules_would_change_is_refused() {
    let rules = with_defaults(vec![rule("bad", r"secret", "7", None)]);
    let error = RuleMasker::new(&rules).unwrap_err().to_string();
    assert!(error.contains("bad") && error.contains("default rules"), "{error}");
    assert!(RuleMasker::new(&[rule("fine", r"secret", "7", None)]).is_ok());
}

#[test]
fn the_number_of_rules_and_the_size_of_a_pattern_are_limited() {
    let many: Vec<MaskRule> =
        (0..=MAX_MASK_RULES).map(|i| rule(&format!("r{i}"), &format!("word{i}x"), "<W>", None)).collect();
    assert!(RuleMasker::new(&many).unwrap_err().to_string().contains("at most"));
    let long = rule("long", &"a".repeat(MAX_PATTERN_BYTES + 1), "<L>", None);
    assert!(RuleMasker::new(&[long]).unwrap_err().to_string().contains("longer"));
    let empty = rule("empty", "a*", "<E>", Some(MaskCheck::Luhn));
    assert!(RuleMasker::new(&[empty]).is_err());
}

#[test]
fn hits_are_positions_in_the_input_and_number_the_rules_in_list_order() {
    let rules = with_defaults(vec![email(), card()]);
    let masker = RuleMasker::new(&rules).unwrap();
    let text = "a 12 bob@example.com 4111111111111111 3";
    let hits = masker.hits(text.as_bytes());
    let seen: Vec<(&str, &str)> = hits.iter().map(|hit| (masker.name(hit.rule), &text[hit.start..hit.end])).collect();
    assert_eq!(seen, [("num", "12"), ("email", "bob@example.com"), ("card", "4111111111111111"), ("num", "3")]);
    let mut rebuilt = String::new();
    let mut cursor = 0;
    for hit in &hits {
        rebuilt.push_str(&text[cursor..hit.start]);
        rebuilt.push_str(std::str::from_utf8(masker.token(hit.rule)).unwrap());
        cursor = hit.end;
    }
    rebuilt.push_str(&text[cursor..]);
    assert_eq!(rebuilt, run(&masker, text));
}

fn piece() -> impl Strategy<Value = String> {
    prop_oneof![
        Just("4111 1111 1111 1111".to_string()),
        Just("4111 1111 1111 1112".to_string()),
        Just("GB82 WEST 1234 5698 7654 32".to_string()),
        Just("GB82 WEST 1234 5698 7654 33".to_string()),
        Just("bob@example.com".to_string()),
        Just("10.0.0.1:80".to_string()),
        Just("/var/log/app.log".to_string()),
        Just("2026-10-04 12:00:01Z".to_string()),
        Just("0xdead".to_string()),
        Just("abcdef12-1234-1234-1234-123456789abc".to_string()),
        "[0-9]{1,8}",
        "[a-zA-Z@._/:+ -]{0,6}",
    ]
}

fn luhn_card(body: &[u8]) -> String {
    let mut sum = 0u32;
    for (index, digit) in body.iter().rev().enumerate() {
        let mut value = u32::from(*digit);
        if index % 2 == 0 {
            value *= 2;
            if value > 9 {
                value -= 9;
            }
        }
        sum += value;
    }
    let check = (10 - sum % 10) % 10;
    body.iter().map(|digit| char::from(b'0' + digit)).chain(std::iter::once(char::from(b'0' + check as u8))).collect()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(256))]

    #[test]
    fn the_scanner_and_the_regex_engine_agree_on_layers(pieces in proptest::collection::vec(piece(), 0..12)) {
        let rules = with_defaults(vec![email(), card(), iban()]);
        let fast = RuleMasker::new(&rules).unwrap();
        let slow = RuleMasker::with_regex(&rules).unwrap();
        prop_assert!(fast.uses_default_scanner() && !slow.uses_default_scanner());
        let text = pieces.join(" ");
        prop_assert_eq!(run(&fast, &text), run(&slow, &text));
        let hits = fast.hits(text.as_bytes());
        let mut rebuilt = String::new();
        let mut cursor = 0;
        for hit in &hits {
            prop_assert!(hit.start >= cursor && hit.end > hit.start);
            rebuilt.push_str(&text[cursor..hit.start]);
            rebuilt.push_str(std::str::from_utf8(fast.token(hit.rule)).unwrap());
            cursor = hit.end;
        }
        rebuilt.push_str(&text[cursor..]);
        prop_assert_eq!(rebuilt, run(&fast, &text));
    }

    #[test]
    fn a_planted_card_never_survives(
        before in "[a-z]{0,8}( [a-z]{1,8}){0,3}",
        after in "[a-z]{0,8}( [a-z]{1,8}){0,3}",
        body in proptest::collection::vec(0u8..10, 15),
    ) {
        let number = luhn_card(&body);
        prop_assert!(MaskCheck::Luhn.accepts(number.as_bytes()));
        let rules = with_defaults(vec![card()]);
        let out = masked(&rules, &format!("{before} {number} {after}"));
        prop_assert!(!out.contains(&number), "{out}");
        prop_assert!(out.contains("<CARD>"), "{out}");
    }
}
