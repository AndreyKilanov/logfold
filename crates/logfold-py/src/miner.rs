//! The live miner of Python: one long-lived native session behind a lock.
//!
//! The class only converts: records come in as lists of strings, one native call per batch, and the work runs with the
//! GIL released. The mining itself lives in `logfold_engine::Session`.

use std::path::Path;
use std::sync::{Mutex, MutexGuard};

use logfold_engine::{EngineError, Session, SessionConfig};
use logfold_io::check_state_writable;
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::convert::{build_output, parse_format, parse_masks, parse_mining, required, sub_dict};
use crate::state::{StateIo, from_dict, parse_state_format};
use crate::translate;

/// The distinct templates that were hit as `(id, text)` pairs, and for every record the index of its template.
type MatchAnswer = (Vec<(String, String)>, Vec<Option<usize>>);

/// A miner that takes records in batches and keeps its templates between calls.
#[pyclass(frozen, module = "logfold._core")]
pub(crate) struct NativeMiner {
    session: Mutex<Session>,
    state: StateIo,
}

impl NativeMiner {
    fn lock(&self) -> Result<MutexGuard<'_, Session>, EngineError> {
        self.session.lock().map_err(|_| EngineError::Config("the miner was left in an unusable state".into()))
    }

    fn with_session<T: Send>(&self, py: Python<'_>, work: impl FnOnce(&mut Session) -> T + Send) -> PyResult<T> {
        py.detach(|| self.lock().map(|mut session| work(&mut session))).map_err(translate)
    }
}

#[pymethods]
impl NativeMiner {
    /// Opens a miner from a request with `format`, `masks`, `mining` and `state` (the file to continue from, if any).
    #[new]
    fn new(py: Python<'_>, request: &Bound<'_, PyDict>) -> PyResult<Self> {
        let state = from_dict(&sub_dict(request, "state")?)?;
        let format = parse_format(&sub_dict(request, "format")?)?;
        let masks = parse_masks(&required(request, "masks")?)?;
        let mining = parse_mining(&sub_dict(request, "mining")?)?;
        let session = py
            .detach(|| {
                let initial = state.read()?;
                Session::new(SessionConfig { format, masks, mining, initial })
            })
            .map_err(translate)?;
        Ok(NativeMiner { session: Mutex::new(session), state })
    }

    /// Mines complete records, one string per record; returns how many were mined.
    fn add_many(&self, py: Python<'_>, records: Vec<String>) -> PyResult<u64> {
        self.with_session(py, |session| session.add_records(records.iter().map(|record| record.as_bytes())))
    }

    /// Mines physical lines, joining continuation lines to the record before them; returns how many records were
    /// completed.
    fn add_lines(&self, py: Python<'_>, lines: Vec<String>) -> PyResult<u64> {
        self.with_session(py, |session| session.add_lines(lines.iter().map(|line| line.as_bytes())))
    }

    /// Mines the record that is still open; returns how many records were mined (0 or 1).
    fn flush(&self, py: Python<'_>) -> PyResult<u64> {
        self.with_session(py, |session| session.flush())
    }

    /// Assigns complete records to the templates of the miner without learning; returns the distinct templates that
    /// were hit as `(id, text)` pairs and, for every record, the index of its template or `None`.
    fn match_many(&self, py: Python<'_>, records: Vec<String>) -> PyResult<MatchAnswer> {
        let batch =
            self.with_session(py, |session| session.match_records(records.iter().map(|record| record.as_bytes())))?;
        let templates = batch.templates.into_iter().map(|template| (template.id, template.text)).collect();
        Ok((templates, batch.assigned))
    }

    /// Texts of the templates created since the previous call, in creation order.
    fn new_templates(&self, py: Python<'_>) -> PyResult<Vec<String>> {
        self.with_session(py, |session| session.take_new_templates())
    }

    /// Returns the templates and the counters of the records mined so far, in the layout of `mine`.
    fn result<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let output = self.with_session(py, |session| session.output())?;
        build_output(py, &output)
    }

    /// Writes the miner as a state file; `state_format` is `json` (the default) or `binary`.
    #[pyo3(signature = (path, state_format=None))]
    fn save_state(&self, py: Python<'_>, path: &str, state_format: Option<&str>) -> PyResult<()> {
        let format = parse_state_format(state_format)?;
        let path = Path::new(path);
        py.detach(|| -> Result<(), EngineError> {
            check_state_writable(path)?;
            let snapshot = self.lock()?.snapshot();
            self.state.write(path, format, snapshot)
        })
        .map_err(translate)
    }
}
