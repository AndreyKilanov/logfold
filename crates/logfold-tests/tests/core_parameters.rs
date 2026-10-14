#![allow(missing_docs)]

//! The values that a message gives to the variable positions of a template.

mod common;

use common::lines;
use logfold_core::{
    Fit, MaskRule, RuleMasker, Tokenizer, WILDCARD, WILDCARD_NAME, default_mask_rules, extract_parameters,
};
use proptest::prelude::*;

type Row = (usize, String, String);

fn run(rules: &[MaskRule], template: &str, message: &str, fit: Fit) -> Option<Vec<Row>> {
    let masker = RuleMasker::new(rules).unwrap();
    let tokenizer = Tokenizer::new(common::DELIMITERS).unwrap();
    let tokens: Vec<&[u8]> =
        if template.is_empty() { Vec::new() } else { template.split(' ').map(str::as_bytes).collect() };
    extract_parameters(&masker, &tokenizer, &tokens, message.as_bytes(), fit).map(|parameters| {
        parameters.into_iter().map(|p| (p.position, p.name, String::from_utf8(p.value).unwrap())).collect()
    })
}

fn exact(template: &str, message: &str) -> Option<Vec<Row>> {
    run(&default_mask_rules(), template, message, Fit::Exact)
}

fn row(position: usize, name: &str, value: &str) -> Row {
    (position, name.to_string(), value.to_string())
}

#[test]
fn masked_values_are_named_by_their_rule_and_given_as_written() {
    let found = exact("user <NUM> logged in from <IP>", "user 42 logged in from 10.0.0.1:8080").unwrap();
    assert_eq!(found, [row(1, "num", "42"), row(5, "ip", "10.0.0.1:8080")]);
}

#[test]
fn a_generalized_position_gives_the_whole_token() {
    let found = exact("login failed for <*>", "login failed for alice").unwrap();
    assert_eq!(found, [row(3, WILDCARD_NAME, "alice")]);
}

#[test]
fn a_masked_value_inside_a_constant_token_is_one_parameter() {
    let found = exact("item id=<NUM> <*>", "item id=17 widget").unwrap();
    assert_eq!(found, [row(1, "num", "17"), row(2, "*", "widget")]);
}

#[test]
fn the_masked_values_inside_a_generalized_token_are_not_given_again() {
    let found = exact("user <*> ok", "user id=7 ok").unwrap();
    assert_eq!(found, [row(1, "*", "id=7")]);
}

#[test]
fn a_rule_that_spans_several_words_gives_one_parameter() {
    let found = exact("<TS> started", "2026-10-04 12:00:01 started").unwrap();
    assert_eq!(found, [row(0, "ts", "2026-10-04 12:00:01")]);
}

#[test]
fn a_generalized_position_after_a_wide_rule_is_aligned_by_the_masked_tokens() {
    let found = exact("<TS> job <*> done in <NUM>", "2026-10-04T12:00:01Z job nightly done in 3.5").unwrap();
    assert_eq!(found, [row(0, "ts", "2026-10-04T12:00:01Z"), row(2, "*", "nightly"), row(5, "num", "3.5")]);
}

#[test]
fn a_message_that_does_not_fit_gives_nothing() {
    assert_eq!(exact("user <NUM> logged in", "user 42 logged out"), None);
    assert_eq!(exact("user <NUM> logged in", "user 42 logged in now"), None);
    assert_eq!(exact("user <NUM> logged in", "user"), None);
    assert_eq!(exact("user <NUM>", "user abc"), None);
}

#[test]
fn by_position_ignores_constant_tokens_that_differ() {
    let found = run(&default_mask_rules(), "user <NUM> logged in", "user 42 logged out", Fit::ByPosition).unwrap();
    assert_eq!(found, [row(1, "num", "42")]);
    assert_eq!(run(&default_mask_rules(), "user <NUM> logged in", "user 42", Fit::ByPosition), None);
}

#[test]
fn without_masks_only_generalized_positions_give_values() {
    let found = run(&[], "id <NUM> is <*>", "id 5 is <NUM>", Fit::Exact);
    assert_eq!(found, None);
    let found = run(&[], "id 5 is <*>", "id 5 is fine", Fit::Exact).unwrap();
    assert_eq!(found, [row(3, "*", "fine")]);
}

#[test]
fn a_template_without_variable_parts_gives_no_parameters() {
    assert_eq!(exact("service started", "service started"), Some(Vec::new()));
    assert_eq!(exact("", ""), Some(Vec::new()));
    assert_eq!(exact("", "   "), Some(Vec::new()));
}

#[test]
fn values_keep_their_non_ascii_text() {
    let found = exact("user <*> from <PATH>", "user Zo\u{eb} \u{4e2d}\u{6587} from /srv/\u{e9}t\u{e9}/log");
    assert_eq!(found, None, "two tokens in a place of one");
    let found = exact("user <*> from <PATH>", "user Zo\u{eb}\u{4e2d} from /srv/log/a").unwrap();
    assert_eq!(found, [row(1, "*", "Zo\u{eb}\u{4e2d}"), row(3, "path", "/srv/log/a")]);
}

#[test]
fn a_custom_rule_is_named_by_its_name() {
    let rules = vec![MaskRule {
        name: "order".into(),
        pattern: r"ORD-\d+".into(),
        token: "<ORDER>".into(),
        ascii: true,
        check: None,
    }];
    let found = run(&rules, "paid <ORDER> by <*>", "paid ORD-9001 by card", Fit::Exact).unwrap();
    assert_eq!(found, [row(1, "order", "ORD-9001"), row(3, "*", "card")]);
}

#[test]
fn the_wildcard_token_is_the_one_of_the_miner() {
    assert_eq!(WILDCARD, b"<*>");
}

fn masked_tokens(message: &str) -> Vec<String> {
    let masker = RuleMasker::new(&default_mask_rules()).unwrap();
    let mut scratch = logfold_core::MaskScratch::default();
    let masked = masker.mask(message.as_bytes(), &mut scratch).to_vec();
    String::from_utf8(masked).unwrap().split_whitespace().map(str::to_string).collect()
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(200))]

    #[test]
    fn a_template_cut_from_a_message_fits_it_and_gives_one_parameter_per_generalized_position(
        message in lines(2).prop_map(|mut all| all.remove(0)),
        keep in prop::collection::vec(any::<bool>(), 12),
    ) {
        let tokens = masked_tokens(&message);
        let template: Vec<String> = tokens
            .iter()
            .enumerate()
            .map(|(i, token)| if keep[i % keep.len()] { token.clone() } else { "<*>".to_string() })
            .collect();
        let generalized = template.iter().filter(|t| t.as_str() == "<*>").count();
        let found = exact(&template.join(" "), &message);
        let found = found.expect("a template cut from the message fits it");
        prop_assert_eq!(found.iter().filter(|(_, name, _)| name == "*").count(), generalized);
        prop_assert!(found.windows(2).all(|pair| pair[0].0 <= pair[1].0));
        prop_assert!(found.iter().all(|(position, _, value)| *position < template.len() && !value.is_empty()));
        prop_assert!(found.iter().all(|(_, _, value)| message.contains(value.as_str())));
        let by_position = run(&default_mask_rules(), &template.join(" "), &message, Fit::ByPosition).unwrap();
        prop_assert_eq!(by_position, found);
    }
}

#[test]
fn a_message_with_very_many_matches_is_aligned_in_linear_time() {
    let count = 200_000;
    let message = (0..count).map(|n| n.to_string()).collect::<Vec<_>>().join(" ");
    let template = vec!["<*>"; count].join(" ");
    let started = std::time::Instant::now();
    let found = exact(&template, &message).unwrap();
    assert_eq!(found.len(), count);
    assert_eq!(found[count - 1], row(count - 1, "*", &(count - 1).to_string()));
    let masked = vec!["<NUM>"; count].join(" ");
    assert_eq!(exact(&masked, &message).unwrap().len(), count);
    assert!(started.elapsed().as_secs() < 20, "alignment is not linear: {:?}", started.elapsed());
}
