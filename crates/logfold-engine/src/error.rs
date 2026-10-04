use logfold_core::CoreError;
use logfold_io::IoError;
use thiserror::Error;

/// Errors of the mining pipeline.
#[derive(Debug, Error)]
pub enum EngineError {
    /// Invalid configuration reported by the domain layer.
    #[error(transparent)]
    Core(#[from] CoreError),
    /// A source could not be read or a format is invalid.
    #[error(transparent)]
    Io(#[from] IoError),
    /// The request is inconsistent.
    #[error("invalid request: {0}")]
    Config(String),
    /// The run was cancelled through the observer.
    #[error("run cancelled")]
    Cancelled,
}
