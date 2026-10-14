#![allow(missing_docs)]

//! Matching records against the templates of a live session: the answers are those of the file command, nothing is
//! learned, and the way the records are cut into batches never changes an answer.

mod common;

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};

use common::lines;
use logfold_core::{MatchRule, MinerSnapshot, default_mask_rules, template_id};
use logfold_engine::{
    ExecutionStrategy, MatchBatch, MineOutput, MineRequest, MiningConfig, NullObserver, Session, SessionConfig,
    match_records,
};
use logfold_io::{FormatConfig, FormatSpec};
use proptest::prelude::*;

fn plain() -> FormatConfig {
    FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false }
}

fn regex() -> FormatConfig {
    FormatConfig {
        spec: FormatSpec::Regex {
            pattern: r"^(?P<lvl>[A-Z]+) (?P<msg>.*)$".into(),
            message_group: Some("msg".into()),
            time_group: None,
            level_group: Some("lvl".into()),
        },
        ts_format: None,
        multiline: false,
    }
}

fn session(format: FormatConfig) -> Session {
    Session::new(SessionConfig { format, masks: default_mask_rules(), mining: MiningConfig::default(), initial: None })
        .unwrap()
}

fn training(count: usize) -> Vec<String> {
    (0..count)
        .map(|n| match n % 4 {
            0 => format!("user u{} logged in from 10.0.{}.{}", n % 97, n % 8, n % 250),
            1 => format!("cache miss for key k{}", n % 1013),
            2 => format!("request {} failed with status {}", n, 500 + n % 4),
            _ => format!("job {} finished", n),
        })
        .collect()
}

fn unknown() -> Vec<String> {
    let long: Vec<String> = (0..30).map(|i| format!("w{}", i % 3)).collect();
    vec![long.join(" "), "a b".to_string(), "totally different words here now".to_string()]
}

fn feed(session: &mut Session, records: &[String]) {
    session.add_records(records.iter().map(|record| record.as_bytes()));
}

fn ask(session: &mut Session, records: &[String]) -> MatchBatch {
    session.match_records(records.iter().map(|record| record.as_bytes()), MatchRule::Similar)
}

fn texts(batch: &MatchBatch) -> Vec<Option<String>> {
    batch.assigned.iter().map(|index| index.map(|index| batch.templates[index].text.clone())).collect()
}

fn from_file(path: &Path, initial: MinerSnapshot) -> MineOutput {
    let request = MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: plain(),
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy: ExecutionStrategy::Sequential,
        warm_start: false,
        recount: false,
        initial: Some(initial),
        keep_snapshot: false,
        values: None,
    };
    match_records(&request, &NullObserver).unwrap()
}

fn write_log(dir: &tempfile::TempDir, records: &[String]) -> PathBuf {
    let path = dir.path().join("a.log");
    std::fs::write(&path, records.join("\n") + "\n").unwrap();
    path
}

#[test]
fn the_answers_are_those_of_the_file_command() {
    let mut live = session(plain());
    feed(&mut live, &training(800));
    let mut probe = training(300);
    probe.extend(unknown());
    let dir = tempfile::tempdir().unwrap();
    let expected = from_file(&write_log(&dir, &probe), live.snapshot());

    let batch = ask(&mut live, &probe);
    let mut counts: BTreeMap<String, u64> = BTreeMap::new();
    for text in texts(&batch).into_iter().flatten() {
        *counts.entry(text).or_default() += 1;
    }
    let unmatched = batch.assigned.iter().filter(|index| index.is_none()).count() as u64;

    let file_counts: BTreeMap<String, u64> =
        expected.templates.iter().map(|template| (template.text.clone(), template.runs[0].count)).collect();
    let file_unmatched: u64 = expected.unmatched.as_ref().unwrap()[0].iter().map(|(_, records)| records).sum();
    assert_eq!(counts, file_counts);
    assert_eq!(unmatched, file_unmatched);
    assert_eq!(unmatched, unknown().len() as u64);
}

#[test]
fn matching_changes_nothing_in_the_session() {
    let mut live = session(plain());
    feed(&mut live, &training(500));
    let before = (live.snapshot(), live.output().runs[0].records, live.output().runs[0].lines);
    let mut probe = training(200);
    probe.extend(unknown());
    ask(&mut live, &probe);
    let after = (live.snapshot(), live.output().runs[0].records, live.output().runs[0].lines);
    assert_eq!(before, after);

    let mut other = session(plain());
    feed(&mut other, &training(500));
    feed(&mut live, &training(100));
    feed(&mut other, &training(100));
    assert_eq!(live.snapshot(), other.snapshot());
}

#[test]
fn an_answer_names_the_template_as_it_is_now() {
    let mut live = session(plain());
    feed(&mut live, &["cache miss for key kab".to_string()]);
    let early = ask(&mut live, &["cache miss for key kab".to_string()]);
    assert_eq!(early.templates[0].text, "cache miss for key kab");
    feed(&mut live, &["cache miss for key kcd".to_string()]);

    let now = ask(&mut live, &["cache miss for key kzz".to_string()]);
    assert_eq!(now.assigned, vec![Some(0)]);
    assert_eq!(now.templates[0].text, "cache miss for key <*>");
    assert_eq!(now.templates[0].id, template_id("cache miss for key <*>"));
    let reported = live.output().templates;
    assert_eq!(
        (reported[0].id.as_str(), reported[0].text.as_str()),
        (now.templates[0].id.as_str(), "cache miss for key <*>")
    );
}

#[test]
fn blank_unparsed_and_unknown_records_have_no_template() {
    let mut live = session(regex());
    feed(&mut live, &["INFO job 1 finished".to_string(), "INFO job 2 finished".to_string()]);
    let records = ["INFO job 3 finished", "", "   ", "no level at all", "WARN something never seen before ever"];
    let batch = live.match_records(records.iter().map(|record| record.as_bytes()), MatchRule::Similar);
    assert_eq!(batch.assigned, vec![Some(0), None, None, None, None]);
    assert_eq!(batch.templates.len(), 1);
    assert_eq!(live.output().runs[0].unparsed, 0);
}

#[test]
fn an_empty_session_and_an_empty_batch_match_nothing() {
    let mut live = session(plain());
    assert_eq!(ask(&mut live, &[]), MatchBatch::default());
    let batch = ask(&mut live, &["job 1 finished".to_string()]);
    assert_eq!(batch.assigned, vec![None]);
    assert!(batch.templates.is_empty());
}

#[test]
fn a_record_that_is_still_open_is_not_touched() {
    let multiline = FormatConfig {
        spec: FormatSpec::Plain { record_start: Some(r"^\d{4}-".to_string()) },
        ts_format: None,
        multiline: true,
    };
    let mut live = session(multiline);
    live.add_lines(["2026-01-01 failure 1\n".as_bytes(), "  at frame 0\n".as_bytes()]);
    let batch = live.match_records(["2026-01-01 failure 2\n  at frame 1".as_bytes()], MatchRule::Similar);
    assert_eq!(batch.assigned, vec![None]);
    assert_eq!(live.flush(), 1);
    let batch = live.match_records(["2026-01-01 failure 2\n  at frame 1".as_bytes()], MatchRule::Similar);
    assert_eq!(batch.assigned, vec![Some(0)]);
}

fn cut<'a>(stream: &'a [String], sizes: &[usize]) -> Vec<&'a [String]> {
    let mut parts = Vec::new();
    let mut rest = stream;
    for size in sizes.iter().cycle() {
        if rest.is_empty() {
            break;
        }
        let (head, tail) = rest.split_at((*size).min(rest.len()));
        parts.push(head);
        rest = tail;
    }
    parts
}

proptest! {
    #![proptest_config(ProptestConfig::with_cases(48))]

    #[test]
    fn any_cut_into_batches_gives_the_same_answers(
        trained in lines(150),
        probe in lines(150),
        sizes in prop::collection::vec(1usize..40, 1..6),
    ) {
        let mut live = session(plain());
        feed(&mut live, &trained);
        let whole = texts(&ask(&mut live, &probe));
        let mut parts = Vec::new();
        for part in cut(&probe, &sizes) {
            parts.extend(texts(&ask(&mut live, part)));
        }
        prop_assert_eq!(parts, whole);
    }

    #[test]
    fn matching_never_changes_the_templates(trained in lines(150), probe in lines(150)) {
        let mut live = session(plain());
        feed(&mut live, &trained);
        let snapshot = live.snapshot();
        let batch = ask(&mut live, &probe);
        prop_assert_eq!(batch.assigned.len(), probe.len());
        prop_assert!(batch.assigned.iter().flatten().all(|index| *index < batch.templates.len()));
        prop_assert_eq!(live.snapshot(), snapshot);
    }

    #[test]
    fn every_trained_record_matches_a_template(trained in lines(150)) {
        let mut live = session(plain());
        feed(&mut live, &trained);
        let batch = ask(&mut live, &trained);
        let blank = |record: &String| record.bytes().all(|byte| byte.is_ascii_whitespace());
        for (record, index) in trained.iter().zip(&batch.assigned) {
            prop_assert_eq!(index.is_none(), blank(record), "record {:?}", record);
        }
    }
}
