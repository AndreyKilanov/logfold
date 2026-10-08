use thiserror::Error;

/// Errors raised while building domain objects from configuration.
#[derive(Debug, Error)]
pub enum CoreError {
    /// A configuration value is outside its allowed range.
    #[error("invalid configuration: {0}")]
    InvalidConfig(String),
    /// A saved miner state is damaged or was not produced by this algorithm.
    #[error("invalid miner state: {0}")]
    InvalidState(String),
    /// A masking rule pattern failed to compile or can match the empty string.
    #[error("invalid mask rule '{name}': {reason}")]
    InvalidRule {
        /// Rule name.
        name: String,
        /// Human readable reason.
        reason: String,
    },
}
