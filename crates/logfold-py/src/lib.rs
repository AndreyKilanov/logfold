//! PyO3 shim exposing the logfold engine to Python as `logfold._core`.
//!
//! The module contains no business logic. It converts a plain-data request into engine types, releases the GIL for the
//! whole run, polls for Ctrl+C and converts the result back into plain Python containers.

mod convert;
mod observer;

use pyo3::exceptions::PyKeyboardInterrupt;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use logfold_engine::{EngineError, MineRequest};
use observer::PyObserver;

/// Version of the Python <-> Rust data contract; bump on any incompatible change of the request or result layout.
const CORE_API_VERSION: u32 = 1;

pyo3::create_exception!(_core, CoreConfigError, pyo3::exceptions::PyException, "Invalid configuration.");
pyo3::create_exception!(_core, CoreFormatError, pyo3::exceptions::PyException, "Invalid or unusable log format.");
pyo3::create_exception!(_core, CoreSourceError, pyo3::exceptions::PyException, "A source could not be read.");

fn translate(error: EngineError) -> PyErr {
    match error {
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
    let request: MineRequest = convert::parse_request(request)?;
    let observer = PyObserver::new(progress);
    let result = py.detach(|| logfold_engine::mine(&request, &observer));
    match result {
        Ok(output) => convert::build_output(py, &output),
        Err(EngineError::Cancelled) => Err(observer.take_error().unwrap_or_else(|| translate(EngineError::Cancelled))),
        Err(other) => Err(translate(other)),
    }
}

/// Pairs templates that exist in one run only; `kind` is `token_subset` or `jaccard` (which needs `threshold`).
///
/// Returns `(before index, after index)` pairs, exactly as the pure-Python matchers do.
#[pyfunction]
#[pyo3(signature = (kind, before, after, threshold=None))]
fn match_templates(
    py: Python<'_>,
    kind: &str,
    before: Vec<String>,
    after: Vec<String>,
    threshold: Option<f64>,
) -> PyResult<Vec<(usize, usize)>> {
    let before: Vec<&str> = before.iter().map(String::as_str).collect();
    let after: Vec<&str> = after.iter().map(String::as_str).collect();
    match kind {
        "token_subset" => Ok(py.detach(|| logfold_core::token_subset_pairs(&before, &after))),
        "jaccard" => {
            let threshold =
                threshold.ok_or_else(|| CoreConfigError::new_err("the jaccard matcher needs a threshold"))?;
            Ok(py.detach(|| logfold_core::jaccard_pairs(&before, &after, threshold)))
        }
        other => Err(CoreConfigError::new_err(format!("unknown matcher {other:?}"))),
    }
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
    m.add_function(wrap_pyfunction!(api_version, m)?)?;
    m.add_function(wrap_pyfunction!(algo_version, m)?)?;
    m.add_function(wrap_pyfunction!(default_masks, m)?)?;
    m.add("CoreConfigError", m.py().get_type::<CoreConfigError>())?;
    m.add("CoreFormatError", m.py().get_type::<CoreFormatError>())?;
    m.add("CoreSourceError", m.py().get_type::<CoreSourceError>())?;
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
