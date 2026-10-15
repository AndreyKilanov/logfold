#![allow(missing_docs)]

//! The distributions of the values of the most frequent templates: collected in the pass over the finished tree, exact
//! for the counters, the same for any number of threads at a fixed chunk size.

use std::io::Write;
use std::path::{Path, PathBuf};

use logfold_core::default_mask_rules;
use logfold_engine::{
    ExecutionStrategy, MineOutput, MineRequest, MiningConfig, NullObserver, TemplateValues, ValuesRequest, mine,
};
use logfold_io::{FormatConfig, FormatSpec};

const PATHS: [&str; 4] = ["home", "login", "search", "cart"];

fn write_log(dir: &tempfile::TempDir, records: usize) -> PathBuf {
    let path = dir.path().join("access.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for n in 0..records {
        let status = if n % 10 == 0 { 404 } else { 200 };
        writeln!(file, "GET /{} {} {}", PATHS[n % PATHS.len()], status, 1 + n % 100).unwrap();
    }
    for n in 0..records / 20 {
        writeln!(file, "worker w{} restarted after {} seconds idle", n % 3, 10 + n % 7).unwrap();
    }
    path
}

fn request(path: &Path, strategy: ExecutionStrategy, values: Option<ValuesRequest>) -> MineRequest {
    MineRequest {
        windows: Vec::new(),
        runs: vec![vec![path.to_path_buf()]],
        format: FormatConfig { spec: FormatSpec::Plain { record_start: None }, ts_format: None, multiline: false },
        masks: default_mask_rules(),
        mining: MiningConfig::default(),
        strategy,
        warm_start: false,
        recount: false,
        initial: None,
        keep_snapshot: false,
        values,
    }
}

fn values_of<'a>(output: &'a MineOutput, prefix: &str) -> &'a TemplateValues {
    output.values.as_ref().unwrap().iter().find(|template| template.text.starts_with(prefix)).unwrap()
}

#[test]
fn the_values_of_the_positions_are_counted_exactly() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, 2000);
    let output = mine(
        &request(&log, ExecutionStrategy::Sequential, Some(ValuesRequest { templates: 10, compare: false })),
        &NullObserver,
    )
    .unwrap();

    let access = values_of(&output, "GET");
    assert_eq!(access.text, "GET <*> <NUM> <NUM>");
    let positions = &access.runs[0];
    assert_eq!(
        positions.iter().map(|p| (p.position, p.name.as_str())).collect::<Vec<_>>(),
        [(1, "*"), (2, "num"), (3, "num")]
    );

    let path = &positions[0].summary;
    assert_eq!(path.count, 2000);
    assert_eq!(path.distinct, 4);
    assert!(path.top.iter().all(|(_, count)| *count == 500));

    let status = &positions[1].summary;
    assert_eq!(status.top, vec![(b"200".to_vec(), 1800), (b"404".to_vec(), 200)]);

    let millis = positions[2].summary.numeric.as_ref().unwrap();
    assert_eq!(millis.count, 2000);
    assert_eq!((millis.min, millis.max), (1.0, 100.0));
    assert!((millis.p50 - 50.0).abs() <= 50.0 * 0.03, "{}", millis.p50);
    assert!((millis.p99 - 99.0).abs() <= 99.0 * 0.03, "{}", millis.p99);

    let counted: u64 = output.templates.iter().find(|t| t.text == access.text).unwrap().runs[0].count;
    assert_eq!(counted, 2000, "the counts of the templates are those of the second pass");
}

#[test]
fn only_the_most_frequent_templates_are_tracked() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, 2000);
    let output = mine(
        &request(&log, ExecutionStrategy::Sequential, Some(ValuesRequest { templates: 1, compare: false })),
        &NullObserver,
    )
    .unwrap();
    let tracked: Vec<&str> = output.values.as_ref().unwrap().iter().map(|t| t.text.as_str()).collect();
    assert_eq!(tracked, ["GET <*> <NUM> <NUM>"]);
}

#[test]
fn nothing_is_collected_without_a_request() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, 300);
    let output = mine(&request(&log, ExecutionStrategy::Sequential, None), &NullObserver).unwrap();
    assert!(output.values.is_none());
}

#[test]
fn the_values_do_not_depend_on_the_number_of_threads_at_a_fixed_chunk_size() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, 6000);
    let run = |threads: usize| {
        let strategy = ExecutionStrategy::Chunked { chunk_bytes: 8 * 1024, threads };
        mine(&request(&log, strategy, Some(ValuesRequest { templates: 10, compare: false })), &NullObserver).unwrap()
    };
    let one = run(1);
    let four = run(4);
    assert_eq!(one.values, four.values);
    assert!(!one.values.as_ref().unwrap().is_empty());
}

#[test]
fn the_sequential_and_the_chunked_runs_count_the_same_values_below_the_cap() {
    let dir = tempfile::tempdir().unwrap();
    let log = write_log(&dir, 6000);
    let sequential = mine(
        &request(&log, ExecutionStrategy::Sequential, Some(ValuesRequest { templates: 10, compare: false })),
        &NullObserver,
    )
    .unwrap();
    let chunked = mine(
        &request(
            &log,
            ExecutionStrategy::Chunked { chunk_bytes: 8 * 1024, threads: 3 },
            Some(ValuesRequest { templates: 10, compare: false }),
        ),
        &NullObserver,
    )
    .unwrap();
    let a = &values_of(&sequential, "GET").runs[0];
    let b = &values_of(&chunked, "GET").runs[0];
    assert_eq!(a[0].summary.top, b[0].summary.top);
    assert_eq!(a[1].summary.top, b[1].summary.top);
    assert_eq!(a[2].summary.numeric, b[2].summary.numeric);
}

#[test]
fn the_values_that_a_mask_set_of_the_user_hides_are_never_counted() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("orders.log");
    let mut file = std::fs::File::create(&path).unwrap();
    for n in 0..300 {
        writeln!(file, "order ORD-{:06} shipped to {} in {} days", n, ["north", "south", "east"][n % 3], 1 + n % 5)
            .unwrap();
    }
    drop(file);
    let mut masks = vec![logfold_core::MaskRule {
        name: "order".into(),
        pattern: "ORD-[0-9]{6}".into(),
        token: "<ORDER>".into(),
        ascii: true,
        check: None,
    }];
    masks.extend(default_mask_rules());
    let mut asked = request(&path, ExecutionStrategy::Sequential, Some(ValuesRequest { templates: 5, compare: false }));
    asked.masks = masks;

    let output = mine(&asked, &NullObserver).unwrap();

    let template = values_of(&output, "order");
    assert_eq!(template.text, "order <ORDER> shipped to <*> in <NUM> days");
    let names: Vec<&str> = template.runs[0].iter().map(|position| position.name.as_str()).collect();
    assert_eq!(names, ["*", "num"], "the order numbers are not listed");
}
