//! State files at the Python boundary: what a request asks to load and to save, and the checks around them.
//!
//! The file formats and their limits live in `logfold-io`; here the request is turned into one load before and one
//! save after the run, so a state never crosses the boundary line by line.

use std::path::{Path, PathBuf};

use logfold_core::{ALGO_VERSION, MinerSnapshot};
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

/// The state file format named by a caller, `json` when none.
pub(crate) fn parse_state_format(name: Option<&str>) -> PyResult<StateFormat> {
    match name {
        None | Some("json") => Ok(StateFormat::Json),
        Some("binary") => Ok(StateFormat::Binary),
        Some(other) => Err(crate::CoreConfigError::new_err(format!("unknown state format '{other}'"))),
    }
}

pub(crate) fn parse(dict: &Bound<'_, PyDict>) -> PyResult<Option<StateIo>> {
    let Some(value) = optional(dict, "state")? else { return Ok(None) };
    from_dict(&value.cast_into::<PyDict>()?).map(Some)
}

/// Reads the description of the state files of a request or of a live miner.
pub(crate) fn from_dict(state: &Bound<'_, PyDict>) -> PyResult<StateIo> {
    let text = |key: &str| -> PyResult<Option<String>> { optional(state, key)?.map(|v| v.extract()).transpose() };
    Ok(StateIo {
        load: text("load")?.map(PathBuf::from),
        save: text("save")?.map(PathBuf::from),
        format: parse_state_format(text("format")?.as_deref())?,
        config_hash: required(state, "config_hash")?.extract()?,
        masks: required(state, "masks")?.extract()?,
        logfold_version: required(state, "logfold_version")?.extract()?,
        log_format: required(state, "log_format")?.extract()?,
    })
}

impl StateIo {
    /// Reads the file to continue from, checks that it was mined with the same algorithm and parameters, and sets it as
    /// the start of the request. Asks the engine for a snapshot when a state is to be saved.
    pub(crate) fn before(&self, request: &mut MineRequest) -> Result<(), EngineError> {
        request.keep_snapshot = self.save.is_some();
        if let Some(path) = &self.save {
            check_state_writable(path)?;
        }
        request.initial = self.read()?;
        Ok(())
    }

    /// Reads the file to continue from and checks that it was mined with the same algorithm and parameters.
    pub(crate) fn read(&self) -> Result<Option<MinerSnapshot>, EngineError> {
        let Some(path) = &self.load else { return Ok(None) };
        let state = read_state_file(path, &StateLimits::default())?;
        state.ensure_compatible(ALGO_VERSION, &self.config_hash)?;
        Ok(Some(state.snapshot))
    }

    /// Writes the trained miner when a state is to be saved.
    pub(crate) fn after(&self, output: &mut MineOutput) -> Result<(), EngineError> {
        let Some(path) = &self.save else { return Ok(()) };
        let snapshot =
            output.snapshot.take().ok_or_else(|| EngineError::Config("the engine returned no snapshot".into()))?;
        self.write(path, self.format, snapshot)
    }

    /// Writes `snapshot` as a state file at `path` in `format`.
    pub(crate) fn write(&self, path: &Path, format: StateFormat, snapshot: MinerSnapshot) -> Result<(), EngineError> {
        let header = StateHeader {
            algo_version: ALGO_VERSION,
            contract: crate::CORE_API_VERSION,
            logfold_version: self.logfold_version.clone(),
            config_hash: self.config_hash.clone(),
            masks: self.masks.clone(),
            format: self.log_format.clone(),
        };
        write_state_file(path, &State { header, snapshot }, format)?;
        Ok(())
    }
}
