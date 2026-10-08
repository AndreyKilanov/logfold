//! State files: a saved miner in JSON or in a compact binary form.
//!
//! A state file holds a header (versions, the fingerprint of masks and parameters, counts) and a
//! [`logfold_core::MinerSnapshot`]. It is an **untrusted input**: sizes are checked against [`StateLimits`] before
//! memory is allocated, a checksum guards against damage, and nothing in it is executed. Both formats carry the same
//! content and are written byte for byte the same way for the same state (`docs/ALGORITHM.md`, state files).

mod binary;
mod json;
mod wire;

use std::fs;
use std::io::Read;
use std::path::{Path, PathBuf};

use flate2::Compression;
use flate2::read::GzDecoder;
use flate2::write::GzEncoder;
use logfold_core::MinerSnapshot;
use thiserror::Error;

pub use wire::StateCounts;

/// Version of the layout of a state file; a file with a newer version is refused.
pub const STATE_SCHEMA_VERSION: u32 = 1;

/// The `kind` field of a JSON state file.
pub const STATE_KIND: &str = "logfold-state";

/// First bytes of a binary state file.
pub const BINARY_MAGIC: &[u8; 8] = b"LFSTATE\0";

/// Longest text of a header field.
pub const MAX_HEADER_TEXT_BYTES: usize = 4096;

/// What a state file says about itself, besides the miner.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct StateHeader {
    /// Version of the algorithm contract the state was mined with.
    pub algo_version: u32,
    /// Version of the extension contract of the logfold that wrote the file.
    pub contract: u32,
    /// Version of the logfold that wrote the file, for information.
    pub logfold_version: String,
    /// Fingerprint of the mining parameters and the masks.
    pub config_hash: String,
    /// Identity of the mask set.
    pub masks: String,
    /// Name of the log format, for information.
    pub format: String,
}

/// A miner with its header.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct State {
    /// Header of the file.
    pub header: StateHeader,
    /// The miner as plain data.
    pub snapshot: MinerSnapshot,
}

/// The two forms of a state file.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum StateFormat {
    /// Readable text.
    Json,
    /// Compact bytes, for very large states.
    Binary,
}

/// Upper bounds checked before memory is allocated.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct StateLimits {
    /// Bytes of the file (after decompression).
    pub max_file_bytes: u64,
    /// Templates, overflow templates included.
    pub max_clusters: u64,
    /// Nodes of the tree.
    pub max_nodes: u64,
    /// Bytes of one token.
    pub max_token_bytes: u64,
    /// Bytes of all tokens together.
    pub max_total_token_bytes: u64,
}

impl Default for StateLimits {
    fn default() -> Self {
        StateLimits {
            max_file_bytes: 1 << 30,
            max_clusters: 1_000_000,
            max_nodes: 4_000_000,
            max_token_bytes: 64 * 1024,
            max_total_token_bytes: 512 << 20,
        }
    }
}

/// Errors of reading and writing a state file.
#[derive(Debug, Error)]
pub enum StateError {
    /// The file cannot be read.
    #[error("cannot read '{path}': {source}")]
    Read {
        /// Path of the file.
        path: PathBuf,
        /// Underlying error.
        source: std::io::Error,
    },
    /// The file cannot be written.
    #[error("cannot write '{path}': {source}")]
    Write {
        /// Path of the file.
        path: PathBuf,
        /// Underlying error.
        source: std::io::Error,
    },
    /// The bytes are neither a JSON nor a binary state file.
    #[error("not a logfold state file")]
    NotState,
    /// The file is damaged or inconsistent.
    #[error("damaged state file: {0}")]
    Damaged(String),
    /// A size in the file is over a limit.
    #[error("the state file is over a limit: {0}")]
    Limit(String),
    /// The file was written by a newer layout.
    #[error("the state file has schema version {found}, this logfold reads up to {supported}")]
    Version {
        /// Version found in the file.
        found: u32,
        /// Newest version this build reads.
        supported: u32,
    },
    /// The content does not match the checksum.
    #[error("the state file does not match its checksum")]
    Checksum,
}

pub(crate) fn damaged(message: impl Into<String>) -> StateError {
    StateError::Damaged(message.into())
}

pub(crate) fn over(message: impl Into<String>) -> StateError {
    StateError::Limit(message.into())
}

/// Encodes a state in the chosen form.
pub fn encode_state(state: &State, format: StateFormat) -> Vec<u8> {
    match format {
        StateFormat::Json => json::encode(state),
        StateFormat::Binary => binary::encode(state),
    }
}

/// Decodes a state; the form is found from the first bytes. Compression is not handled here, see [`read_state_file`].
pub fn decode_state(bytes: &[u8], limits: &StateLimits) -> Result<State, StateError> {
    if bytes.len() as u64 > limits.max_file_bytes {
        return Err(over(format!("{} bytes, at most {}", bytes.len(), limits.max_file_bytes)));
    }
    if bytes.starts_with(BINARY_MAGIC) {
        binary::decode(bytes, limits)
    } else if bytes.first() == Some(&b'{') {
        json::decode(bytes, limits)
    } else {
        Err(StateError::NotState)
    }
}

/// Reads a state file; a gzip file is decompressed with the size limit applied to the decompressed bytes.
pub fn read_state_file(path: &Path, limits: &StateLimits) -> Result<State, StateError> {
    let read_error = |source| StateError::Read { path: path.to_path_buf(), source };
    let raw = fs::metadata(path).map_err(read_error)?.len();
    let gz = path.extension().is_some_and(|ext| ext.eq_ignore_ascii_case("gz"));
    if raw > limits.max_file_bytes && !gz {
        return Err(over(format!("{raw} bytes, at most {}", limits.max_file_bytes)));
    }
    let file = fs::File::open(path).map_err(read_error)?;
    let mut bytes = Vec::new();
    let cap = limits.max_file_bytes + 1;
    if gz {
        GzDecoder::new(file).take(cap).read_to_end(&mut bytes).map_err(read_error)?;
    } else {
        file.take(cap).read_to_end(&mut bytes).map_err(read_error)?;
    }
    decode_state(&bytes, limits)
}

/// The file a state is written to first, next to the target; the process id keeps two writers apart.
fn staging_path(path: &Path) -> PathBuf {
    let mut staging = path.as_os_str().to_owned();
    staging.push(format!(".{}.part", std::process::id()));
    PathBuf::from(staging)
}

/// Checks that a state can be written to `path`, by creating and removing its staging file. A long run asks for this
/// before it starts, so that a mistyped folder does not cost the whole run.
pub fn check_state_writable(path: &Path) -> Result<(), StateError> {
    let staging = staging_path(path);
    let write_error = |source| StateError::Write { path: path.to_path_buf(), source };
    fs::File::create(&staging).map_err(write_error)?;
    fs::remove_file(&staging).map_err(write_error)
}

/// Writes a state file; a path that ends in `.gz` is compressed. The file appears whole or not at all.
pub fn write_state_file(path: &Path, state: &State, format: StateFormat) -> Result<(), StateError> {
    let write_error = |source| StateError::Write { path: path.to_path_buf(), source };
    let bytes = encode_state(state, format);
    let bytes = if path.extension().is_some_and(|ext| ext.eq_ignore_ascii_case("gz")) {
        use std::io::Write;
        let mut encoder = GzEncoder::new(Vec::new(), Compression::default());
        encoder.write_all(&bytes).map_err(write_error)?;
        encoder.finish().map_err(write_error)?
    } else {
        bytes
    };
    let staging = staging_path(path);
    fs::write(&staging, &bytes).map_err(write_error)?;
    fs::rename(&staging, path).map_err(|source| {
        let _ = fs::remove_file(&staging);
        StateError::Write { path: path.to_path_buf(), source }
    })
}
