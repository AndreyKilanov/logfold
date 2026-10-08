#![allow(missing_docs)]

use logfold_core::Matcher;

const RULES: &[(&str, &str)] = &[("a <*>", "b <*>")];

#[test]
fn every_name_builds_its_matcher() {
    assert_eq!(Matcher::from_name("exact", None, None).unwrap(), Matcher::Exact);
    assert_eq!(Matcher::from_name("token_subset", None, None).unwrap(), Matcher::TokenSubset);
    assert_eq!(Matcher::from_name("jaccard", Some(0.5), None).unwrap(), Matcher::Jaccard(0.5));
    assert_eq!(Matcher::from_name("jaccard_idf", Some(0.6), None).unwrap(), Matcher::JaccardIdf(0.6));
    assert_eq!(Matcher::from_name("overlap", Some(0.7), None).unwrap(), Matcher::Overlap(0.7));
    assert_eq!(Matcher::from_name("rules", None, Some(RULES)).unwrap(), Matcher::Rules(RULES));
}

#[test]
fn parameters_that_a_matcher_ignores_are_ignored() {
    assert_eq!(Matcher::from_name("exact", Some(0.5), Some(RULES)).unwrap(), Matcher::Exact);
    assert_eq!(Matcher::from_name("token_subset", Some(0.5), Some(RULES)).unwrap(), Matcher::TokenSubset);
}

#[test]
fn a_missing_parameter_is_named_in_the_error() {
    for name in ["jaccard", "jaccard_idf", "overlap"] {
        let message = Matcher::from_name(name, None, None).unwrap_err().to_string();
        assert!(message.contains(&format!("the {name} matcher needs a threshold")), "{message}");
    }
    let message = Matcher::from_name("rules", Some(0.5), None).unwrap_err().to_string();
    assert!(message.contains("the rules matcher needs rules"), "{message}");
}

#[test]
fn an_unknown_name_is_an_error() {
    let message = Matcher::from_name("nope", Some(0.5), Some(RULES)).unwrap_err().to_string();
    assert!(message.contains("unknown matcher \"nope\""), "{message}");
}

#[test]
fn pairs_dispatches_to_the_named_matcher() {
    let before = ["a b c d"];
    let after = ["a b c e"];
    assert!(Matcher::Exact.pairs(&before, &after).is_empty());
    assert_eq!(Matcher::Jaccard(0.5).pairs(&before, &after), logfold_core::jaccard_pairs(&before, &after, 0.5));
    assert_eq!(Matcher::TokenSubset.pairs(&before, &after), logfold_core::token_subset_pairs(&before, &after));
}
