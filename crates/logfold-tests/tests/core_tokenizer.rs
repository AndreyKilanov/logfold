#![allow(missing_docs)]

use logfold_core::*;

#[test]
fn splits_on_delimiters_and_skips_empty() {
    let tok = Tokenizer::new(b" \t").unwrap();
    let mut spans = Vec::new();
    tok.tokenize(b"  a bb\t\tccc ", &mut spans);
    let view = TokenView::new(b"  a bb\t\tccc ", &spans);
    assert_eq!(view.len(), 3);
    assert_eq!(view.get(0), b"a");
    assert_eq!(view.get(1), b"bb");
    assert_eq!(view.get(2), b"ccc");
}

#[test]
fn empty_input_has_no_tokens() {
    let tok = Tokenizer::new(b" ").unwrap();
    let mut spans = Vec::new();
    tok.tokenize(b"", &mut spans);
    assert!(spans.is_empty());
}

#[test]
fn rejects_non_ascii_delimiters() {
    assert!(Tokenizer::new("é".as_bytes()).is_err());
}
