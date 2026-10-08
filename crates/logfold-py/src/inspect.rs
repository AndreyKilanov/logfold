//! `inspect_sample`: how a format reads the start of a log.

use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use logfold_core::Level;
use logfold_engine::{SampleReport, inspect_sample};

use crate::convert::parse_format;
use crate::translate;

/// Reads `sample` with the format given as a dict and reports the counts and the first `keep` records.
#[pyfunction]
#[pyo3(name = "inspect_sample")]
pub(crate) fn inspect<'py>(
    py: Python<'py>,
    sample: &[u8],
    format: &Bound<'py, PyDict>,
    keep: usize,
) -> PyResult<Bound<'py, PyDict>> {
    let config = parse_format(format)?;
    let report = py.detach(|| inspect_sample(&config, sample, keep)).map_err(translate)?;
    build(py, &report)
}

fn level_name(level: Option<Level>) -> Option<&'static str> {
    level.map(|level| Level::NAMES[level.rank()])
}

fn build<'py>(py: Python<'py>, report: &SampleReport) -> PyResult<Bound<'py, PyDict>> {
    let shown = PyList::empty(py);
    for record in &report.shown {
        let item = PyDict::new(py);
        item.set_item("message", &record.message)?;
        item.set_item("time", record.timestamp)?;
        item.set_item("tz_aware", record.tz_aware)?;
        item.set_item("level", level_name(record.level))?;
        item.set_item("lines", record.lines)?;
        shown.append(item)?;
    }
    let levels = PyDict::new(py);
    for (rank, count) in report.levels.iter().enumerate() {
        if *count > 0 {
            levels.set_item(Level::NAMES[rank], count)?;
        }
    }
    let answer = PyDict::new(py);
    answer.set_item("shown", shown)?;
    answer.set_item("lines", report.lines)?;
    answer.set_item("records", report.records)?;
    answer.set_item("unparsed", report.unparsed)?;
    answer.set_item("levels", levels)?;
    answer.set_item("no_level", report.no_level)?;
    answer.set_item("first", report.first)?;
    answer.set_item("last", report.last)?;
    answer.set_item("tz_aware", report.tz_aware)?;
    Ok(answer)
}
