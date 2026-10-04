use std::path::PathBuf;

use thiserror::Error;

/// Errors of the I/O layer.
#[derive(Debug, Error)]
pub enum IoError {
    /// Reading a source failed.
    #[error("cannot read '{path}': {source}")]
    Read {
        /// Path of the source.
        path: PathBuf,
        /// Underlying error.
        source: std::io::Error,
    },
    /// The format specification is invalid.
    #[error("invalid format: {0}")]
    Format(String),
}
