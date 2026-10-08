//! State files at the Python boundary: what a request asks to load and to save, and the checks around them.
//!
//! The file formats and their limits live in `logfold-io`; here the request is turned into one load before and one
//! save after the run, so a state never crosses the boundary line by line.

use std::path::PathBuf;

use logfold_core::ALGO_VERSION;
use logfold_engine::{EngineError, MineOutput, MineRequest};
use logfold_io::{
    State, StateFormat, StateHeader, StateLimits, check_state_writable, read_state_file, write_state_file,
};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::convert::{optional, required};

/// What a request asks of the state files.
pub(crate) struct StateIo {
    load: Option<PathBuf>,
    save: Option<PathBuf>,
    format: StateFormat,
    config_hash: String,
    masks: String,
    logfold_version: String,
    log_format: String,
}

pub(crate) fn parse(dict: &Bound<'_, PyDict>) -> PyResult<Option<StateIo>> {
    let Some(value) = optional(dict, "state")? else { return Ok(None) };
    let state = value.cast_into::<PyDict>()?;
    let text = |key: &str| -> PyResult<Option<String>> { optional(&state, key)?.map(|v| v.extract()).transpose() };
    let format = match text("format")?.as_deref() {
        None | Some("json") => StateFormat::Json,
        Some("binary") => StateFormat::Binary,
        Some(other) => return Err(crate::CoreConfigError::new_err(format!("unknown state format '{other}'"))),
    };
    Ok(Some(StateIo {
        load: text("load")?.map(PathBuf::from),
        save: text("save")?.map(PathBuf::from),
        format,
        config_hash: required(&state, "config_hash")?.extract()?,
        masks: required(&state, "masks")?.extract()?,
        logfold_version: required(&state, "logfold_version")?.extract()?,
        log_format: required(&state, "log_format")?.extract()?,
    }))
}

impl StateIo {
    /// Reads the file to continue from, checks that it was mined with the same algorithm and parameters, and sets it as
    /// the start of the request. Asks the engine for a snapshot when a state is to be saved.
    pub(crate) fn before(&self, request: &mut MineRequest) -> Result<(), EngineError> {
        request.keep_snapshot = self.save.is_some();
        if let Some(path) = &self.save {
            check_state_writable(path)?;
        }
        let Some(path) = &self.load else { return Ok(()) };
        let state = read_state_file(path, &StateLimits::default())?;
        state.ensure_compatible(ALGO_VERSION, &self.config_hash)?;
        request.initial = Some(state.snapshot);
        Ok(())
    }

    /// Writes the trained miner when a state is to be saved.
    pub(crate) fn after(&self, output: &mut MineOutput) -> Result<(), EngineError> {
        let Some(path) = &self.save else { return Ok(()) };
        let snapshot =
            output.snapshot.take().ok_or_else(|| EngineError::Config("the engine returned no snapshot".into()))?;
        let header = StateHeader {
            algo_version: ALGO_VERSION,
            contract: crate::CORE_API_VERSION,
            logfold_version: self.logfold_version.clone(),
            config_hash: self.config_hash.clone(),
            masks: self.masks.clone(),
            format: self.log_format.clone(),
        };
        write_state_file(path, &State { header, snapshot }, self.format)?;
        Ok(())
    }
}
