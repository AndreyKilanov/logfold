use std::path::PathBuf;

use logfold_io::{inspect, SourceInfo};

use crate::error::EngineError;
use crate::request::MineRequest;

/// One contiguous piece of work: a byte range of one file belonging to one run.
pub(crate) struct Unit {
    pub(crate) run: usize,
    pub(crate) path: PathBuf,
    pub(crate) info: SourceInfo,
    pub(crate) start: u64,
    pub(crate) end: u64,
}

/// The ordered work list plus per-run input sizes.
pub(crate) struct Plan {
    pub(crate) units: Vec<Unit>,
    pub(crate) run_bytes: Vec<u64>,
}

/// Plans units in run, file, offset order. Without `chunk_bytes` every file is a single unit.
pub(crate) fn plan(request: &MineRequest, chunk_bytes: Option<u64>) -> Result<Plan, EngineError> {
    if chunk_bytes == Some(0) {
        return Err(EngineError::Config("chunk size must be positive".into()));
    }
    let mut units = Vec::new();
    let mut run_bytes = vec![0u64; request.runs.len()];
    for (run, files) in request.runs.iter().enumerate() {
        for path in files {
            let info = inspect(path)?;
            run_bytes[run] += info.size;
            let splittable = info.seekable() && chunk_bytes.is_some_and(|chunk| info.size > chunk);
            if splittable {
                let chunk = chunk_bytes.unwrap_or(u64::MAX);
                let count = info.size.div_ceil(chunk);
                for index in 0..count {
                    let end = if index + 1 == count { u64::MAX } else { (index + 1) * chunk };
                    units.push(Unit { run, path: path.clone(), info, start: index * chunk, end });
                }
            } else if !(info.seekable() && info.size == 0) {
                units.push(Unit { run, path: path.clone(), info, start: 0, end: u64::MAX });
            }
        }
    }
    Ok(Plan { units, run_bytes })
}
