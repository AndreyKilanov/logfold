//! PyO3 shim exposing the logfold engine to Python as `logfold._core`.
//!
//! The module contains no business logic. It converts a plain-data request into engine types, releases the GIL for the
//! whole run, polls for Ctrl+C and converts the result back into plain Python containers.

mod convert;
mod observer;
mod report;
mod state;

use pyo3::exceptions::PyKeyboardInterrupt;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use logfold_engine::{EngineError, MineRequest};
use observer::PyObserver;

/// Version of the Python <-> Rust data contract; bump on any incompatible change of the request or result layout.
const CORE_API_VERSION: u32 = 8;

pyo3::create_exception!(_core, CoreConfigError, pyo3::exceptions::PyException, "Invalid configuration.");
pyo3::create_exception!(_core, CoreFormatError, pyo3::exceptions::PyException, "Invalid or unusable log format.");
pyo3::create_exception!(_core, CoreSourceError, pyo3::exceptions::PyException, "A source could not be read.");
pyo3::create_exception!(_core, CoreStateError, pyo3::exceptions::PyException, "A state file cannot be used.");

fn translate(error: EngineError) -> PyErr {
    match error {
        EngineError::Core(e @ logfold_core::CoreError::InvalidState(_)) => CoreStateError::new_err(e.to_string()),
        EngineError::Core(e) => CoreConfigError::new_err(e.to_string()),
        EngineError::Config(message) => CoreConfigError::new_err(message),
        EngineError::Io(e @ logfold_io::IoError::Format(_)) => CoreFormatError::new_err(e.to_string()),
        EngineError::Io(e) => CoreSourceError::new_err(e.to_string()),
        EngineError::Cancelled => PyKeyboardInterrupt::new_err("run cancelled"),
    }
}

/// Mines templates from one or more runs. `progress`, when given, is called with consumed byte counts.
#[pyfunction]
#[pyo3(signature = (request, progress=None))]
fn mine<'py>(
    py: Python<'py>,
    request: &Bound<'py, PyDict>,
    progress: Option<Py<PyAny>>,
) -> PyResult<Bound<'py, PyDict>> {
    let (mut request, state): (MineRequest, _) = convert::parse_request(request)?;
    let observer = PyObserver::new(progress);
    let result = py.detach(|| run(&mut request, state.as_ref(), &observer));
    match result {
        Ok(output) => convert::build_output(py, &output),
        Err(Failure::Engine(EngineError::Cancelled)) => {
            Err(observer.take_error().unwrap_or_else(|| translate(EngineError::Cancelled)))
        }
        Err(Failure::Engine(other)) => Err(translate(other)),
        Err(Failure::State(failure)) => Err(CoreStateError::new_err(failure.0)),
    }
}

enum Failure {
    Engine(EngineError),
    State(state::StateFailure),
}

/// One load of the state to continue from, the mining run, and one save of the state: a state never crosses the
/// boundary line by line.
fn run(
    request: &mut MineRequest,
    state: Option<&state::StateIo>,
    observer: &PyObserver,
) -> Result<logfold_engine::MineOutput, Failure> {
    if let Some(state) = state {
        state.before(request).map_err(Failure::State)?;
    }
    let mut output = logfold_engine::mine(request, observer).map_err(Failure::Engine)?;
    if let Some(state) = state {
        state.after(&mut output).map_err(Failure::State)?;
    }
    Ok(output)
}

/// Pairs templates that exist in one run only.
///
/// `kind` is `token_subset`; `jaccard`, `jaccard_idf` or `overlap` (which need `threshold`); or `rules` (which needs
/// `rules`, a list of `(left, right)` template texts). Returns `(before index, after index)` pairs, exactly as the
/// pure-Python matchers do.
#[pyfunction]
#[pyo3(signature = (kind, before, after, threshold=None, rules=None))]
fn match_templates(
    py: Python<'_>,
    kind: &str,
    before: Vec<String>,
    after: Vec<String>,
    threshold: Option<f64>,
    rules: Option<Vec<(String, String)>>,
) -> PyResult<Vec<(usize, usize)>> {
    let before: Vec<&str> = before.iter().map(String::as_str).collect();
    let after: Vec<&str> = after.iter().map(String::as_str).collect();
    let need =
        |kind: &str| threshold.ok_or_else(|| CoreConfigError::new_err(format!("the {kind} matcher needs a threshold")));
    match kind {
        "token_subset" => Ok(py.detach(|| logfold_core::token_subset_pairs(&before, &after))),
        "jaccard" => {
            let threshold = need("jaccard")?;
            Ok(py.detach(|| logfold_core::jaccard_pairs(&before, &after, threshold)))
        }
        "jaccard_idf" => {
            let threshold = need("jaccard_idf")?;
            Ok(py.detach(|| logfold_core::jaccard_idf_pairs(&before, &after, threshold)))
        }
        "overlap" => {
            let threshold = need("overlap")?;
            Ok(py.detach(|| logfold_core::overlap_pairs(&before, &after, threshold)))
        }
        "rules" => {
            let rules = rules.ok_or_else(|| CoreConfigError::new_err("the rules matcher needs rules"))?;
            let rules: Vec<(&str, &str)> = rules.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect();
            Ok(py.detach(|| logfold_core::rules_pairs(&before, &after, &rules)))
        }
        other => Err(CoreConfigError::new_err(format!("unknown matcher {other:?}"))),
    }
}

/// Splits the templates of two runs into new, disappeared, changed and unchanged (`docs/ALGORITHM.md` §11).
///
/// `matcher` is `exact`, `token_subset`, `jaccard`, `jaccard_idf` or `overlap` (the last three need `threshold`), or
/// `rules` (which needs `rules`). Returns `(new, disappeared, changed, unchanged)`: indices into the passed columns, and for every changed template `(before index, after index, before
/// share, after share, ratio or None)`, each list sorted most significant first.
#[pyfunction]
#[pyo3(signature = (before_texts, before_counts, before_total, after_texts, after_counts, after_total, ratio,
                    min_count, min_new_count, matcher, threshold=None, rules=None))]
#[expect(clippy::too_many_arguments, clippy::type_complexity)]
fn compare_runs(
    py: Python<'_>,
    before_texts: Vec<String>,
    before_counts: Vec<u64>,
    before_total: u64,
    after_texts: Vec<String>,
    after_counts: Vec<u64>,
    after_total: u64,
    ratio: f64,
    min_count: u64,
    min_new_count: u64,
    matcher: &str,
    threshold: Option<f64>,
    rules: Option<Vec<(String, String)>>,
) -> PyResult<(Vec<usize>, Vec<usize>, Vec<(usize, usize, f64, f64, Option<f64>)>, usize)> {
    if before_texts.len() != before_counts.len() || after_texts.len() != after_counts.len() {
        return Err(CoreConfigError::new_err("every template needs a text and a count"));
    }
    let need =
        |kind: &str| threshold.ok_or_else(|| CoreConfigError::new_err(format!("the {kind} matcher needs a threshold")));
    let rule_texts: Vec<(&str, &str)> = match (matcher, &rules) {
        ("rules", Some(rules)) => rules.iter().map(|(a, b)| (a.as_str(), b.as_str())).collect(),
        ("rules", None) => return Err(CoreConfigError::new_err("the rules matcher needs rules")),
        _ => Vec::new(),
    };
    let matcher = match matcher {
        "exact" => logfold_core::Matcher::Exact,
        "token_subset" => logfold_core::Matcher::TokenSubset,
        "jaccard" => logfold_core::Matcher::Jaccard(need("jaccard")?),
        "jaccard_idf" => logfold_core::Matcher::JaccardIdf(need("jaccard_idf")?),
        "overlap" => logfold_core::Matcher::Overlap(need("overlap")?),
        "rules" => logfold_core::Matcher::Rules(&rule_texts),
        other => return Err(CoreConfigError::new_err(format!("unknown matcher {other:?}"))),
    };
    let before_refs: Vec<&str> = before_texts.iter().map(String::as_str).collect();
    let after_refs: Vec<&str> = after_texts.iter().map(String::as_str).collect();
    let thresholds = logfold_core::Thresholds { ratio, min_count, min_new_count };
    let comparison = py.detach(|| {
        let before = logfold_core::Side { texts: &before_refs, counts: &before_counts, total: before_total };
        let after = logfold_core::Side { texts: &after_refs, counts: &after_counts, total: after_total };
        logfold_core::compare_runs(&before, &after, &thresholds, matcher)
    });
    let changed = comparison
        .changed
        .into_iter()
        .map(|entry| (entry.before, entry.after, entry.before_share, entry.after_share, entry.ratio))
        .collect();
    Ok((comparison.new, comparison.disappeared, changed, comparison.unchanged))
}

/// Renders a pipeline report (`github-summary`, `junit`, `chat-message` or `prometheus`) of a result given as columns
/// (`docs/ALGORITHM.md` section 12). `options` holds `top` and, for `github-summary` and `chat-message`, the size limit
/// `max_bytes` or `max_chars`. The text equals the one of the pure-Python reporter of the same name.
#[pyfunction]
fn render_report(report: &str, data: &Bound<'_, PyDict>, options: &Bound<'_, PyDict>) -> PyResult<String> {
    report::render(report, data, options)
}

/// Returns the version of the Python <-> Rust data contract.
#[pyfunction]
fn api_version() -> u32 {
    CORE_API_VERSION
}

/// Returns the version of the algorithm contract (`docs/ALGORITHM.md`).
#[pyfunction]
fn algo_version() -> u32 {
    logfold_core::ALGO_VERSION
}

/// Returns the default mask rules as a list of dicts.
#[pyfunction]
fn default_masks(py: Python<'_>) -> PyResult<Bound<'_, PyList>> {
    let list = PyList::empty(py);
    for rule in logfold_core::default_mask_rules() {
        let item = PyDict::new(py);
        item.set_item("name", rule.name)?;
        item.set_item("pattern", rule.pattern)?;
        item.set_item("token", rule.token)?;
        item.set_item("ascii", rule.ascii)?;
        list.append(item)?;
    }
    Ok(list)
}

/// Native engine of logfold.
#[pymodule]
fn _core(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(mine, m)?)?;
    m.add_function(wrap_pyfunction!(match_templates, m)?)?;
    m.add_function(wrap_pyfunction!(compare_runs, m)?)?;
    m.add_function(wrap_pyfunction!(render_report, m)?)?;
    m.add_function(wrap_pyfunction!(api_version, m)?)?;
    m.add_function(wrap_pyfunction!(algo_version, m)?)?;
    m.add_function(wrap_pyfunction!(default_masks, m)?)?;
    m.add("CoreConfigError", m.py().get_type::<CoreConfigError>())?;
    m.add("CoreFormatError", m.py().get_type::<CoreFormatError>())?;
    m.add("CoreSourceError", m.py().get_type::<CoreSourceError>())?;
    m.add("CoreStateError", m.py().get_type::<CoreStateError>())?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
