#![allow(missing_docs)]

//! The strict matching rule: a record belongs to a template only when every constant token of the template equals the
//! token of the record. It is checked against a brute-force oracle over the templates, and against the file command.

mod common;

use std::path::{Path, PathBuf};

use common::lines;
use logfold_core::{MatchRule, MinerSnapshot};
use logfold_engine::{
    ExecutionStrategy, MatchBatch, MineOutput, MineRequest, MiningConfig, NullObserver, Session, SessionConfig,
    match_records_with,
};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

fn plain() -> FormatConfig {
    FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false }
}

fn session(masks: Vec<logfold_core::MaskRule>) -> Session {
    Session::new(SessionConfig { format: plain(), masks, mining: MiningConfig::default(), initial: None }).unwrap()
}

fn feed(session: &mut Session, records: &[String]) {
    session.add_records(records.iter().map(|record| record.as_bytes()));
}

fn ask(session: &mut Session, records: &[String], rule: MatchRule) -> MatchBatch {
    session.match_records(records.iter().map(|record| record.as_bytes()), rule)
}

fn texts(batch: &MatchBatch) -> Vec<Option<String>> {
    batch.assigned.iter().map(|index| index.map(|index| batch.templates[index].text.clone())).collect()
}

fn fits(template: &str, record: &str) -> Option<usize> {
    let template: Vec<&str> = template.split(' ').collect();
    let record: Vec<&str> = record.split_whitespace().collect();
    if template.len() != record.len() {
        return None;
    }
    let mut wildcards = 0;
    for (constant, token) in template.iter().zip(&record) {
        if *constant == "<*>" {
            wildcards += 1;
        } else if constant != token {
            return None;
        }
    }
    Some(wildcards)
}

#[test]
fn a_record_that_differs_in_a_constant_word_has_no_template() {
    let mut live = session(logfold_core::default_mask_rules());
    feed(
        &mut live,
        &["user alice logged in from 10.0.0.1".to_string(), "user bob logged in from 10.0.0.2".to_string()],
    );
    let probe: Vec<String> =
        ["user carol logged in from 10.0.0.3", "user carol logged out from 10.0.0.3", "disk is full"]
            .iter()
            .map(|line| line.to_string())
            .collect();

    let strict = texts(&ask(&mut live, &probe, MatchRule::Exact));
    let loose = texts(&ask(&mut live, &probe, MatchRule::Similar));

    let template = Some("user <*> logged in from <IP>".to_string());
    assert_eq!(strict, vec![template.clone(), None, None]);
    assert_eq!(loose, vec![template.clone(), template, None]);
}

#[test]
fn a_wildcard_accepts_any_token_and_a_constant_accepts_only_itself() {
    let mut live = session(Vec::new());
    feed(&mut live, &["a b c d e".to_string(), "a b c d f".to_string()]);
    let probe: Vec<String> =
        ["a b c d zzz", "a b c x e", "a b c d", "a b c d e f"].iter().map(|line| line.to_string()).collect();
    let strict = texts(&ask(&mut live, &probe, MatchRule::Exact));
    assert_eq!(strict, vec![Some("a b c d <*>".to_string()), None, None, None]);
    let loose = texts(&ask(&mut live, &probe, MatchRule::Similar));
    assert_eq!(loose[1], Some("a b c d <*>".to_string()));
}

#[test]
fn matching_exactly_changes_nothing_in_the_session() {
    let mut live = session(Vec::new());
    feed(&mut live, &["a b c".to_string(), "a b d".to_string(), "e f g".to_string()]);
    let before = live.snapshot();
    ask(&mut live, &["a b z".to_string(), "q".to_string()], MatchRule::Exact);
    assert_eq!(live.snapshot(), before);
}

fn from_file(path: &Path, initial: MinerSnapshot, rule: MatchRule) -> MineOutput {
    let request = MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: plain(),
        masks: Vec::new(),
        mining: MiningConfig::default(),
        strategy: ExecutionStrategy::Sequential,
        warm_start: false,
        recount: false,
        initial: Some(initial),
        keep_snapshot: false,
    };
    match_records_with(&request, &NullObserver, rule).unwrap()
}

fn write_log(dir: &tempfile::TempDir, records: &[String]) -> PathBuf {
    let path = dir.path().join("a.log");
    std::fs::write(&path, records.join("\n") + "\n").unwrap();
    path
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(64))]

    #[test]
    fn a_record_has_a_template_exactly_when_one_fits_it(trained in lines(120), probe in lines(120)) {
        let mut live = session(Vec::new());
        feed(&mut live, &trained);
        let templates: Vec<String> = live.output().templates.into_iter().map(|template| template.text).collect();
        let answers = texts(&ask(&mut live, &probe, MatchRule::Exact));
        for (record, answer) in probe.iter().zip(&answers) {
            let fitting: Vec<&String> = templates.iter().filter(|template| fits(template, record).is_some()).collect();
            match answer {
                Some(text) => prop_assert!(fits(text, record).is_some(), "{text:?} does not fit {record:?}"),
                None => prop_assert!(fitting.is_empty(), "{record:?} fits {fitting:?}"),
            }
        }
    }

    #[test]
    fn every_trained_record_has_an_exact_template(trained in lines(120)) {
        let mut live = session(Vec::new());
        feed(&mut live, &trained);
        let answers = ask(&mut live, &trained, MatchRule::Exact).assigned;
        prop_assert!(answers.iter().all(Option::is_some));
    }

    #[test]
    fn the_answers_are_those_of_the_file_command_and_do_not_depend_on_the_batches(
        trained in lines(120),
        probe in lines(120),
        size in 1usize..30,
    ) {
        let mut live = session(Vec::new());
        feed(&mut live, &trained);
        let whole = texts(&ask(&mut live, &probe, MatchRule::Exact));
        let mut parts = Vec::new();
        for part in probe.chunks(size) {
            parts.extend(texts(&ask(&mut live, part, MatchRule::Exact)));
        }
        prop_assert_eq!(&parts, &whole);

        let dir = tempfile::tempdir().unwrap();
        let output = from_file(&write_log(&dir, &probe), live.snapshot(), MatchRule::Exact);
        let unmatched: u64 = output.unmatched.as_ref().unwrap()[0].iter().map(|(_, records)| records).sum();
        prop_assert_eq!(unmatched, whole.iter().filter(|answer| answer.is_none()).count() as u64);
        let hits: u64 = output.templates.iter().map(|template| template.runs[0].count).sum();
        prop_assert_eq!(hits, whole.iter().filter(|answer| answer.is_some()).count() as u64);
    }
}
