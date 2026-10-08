//! I/O adapters of logfold: byte sources, line framing, log formats and timestamps.
//!
//! Everything that touches files, compression or the textual layout of a log lives here. The crate depends on
//! `logfold-core` only for domain types such as [`logfold_core::Level`].

#![forbid(unsafe_code)]

mod error;
mod format;
mod lines;
mod records;
mod source;
mod state;
mod timestamp;

pub use error::IoError;
pub use format::{CompiledFormat, FormatConfig, FormatSpec, ParsedRecord};
pub use lines::{INITIAL_WINDOW, Line, LineReader, MAX_LINE_BYTES};
pub use records::{
    Counters, MAX_RECORD_BYTES, Placement, ScanOutcome, ScanWindow, TICK_BYTES, TimeWindow, scan_records,
};
pub use source::{Compression, STDIN_PATH, SourceInfo, inspect, open_source};
pub use state::{
    BINARY_MAGIC, MAX_HEADER_TEXT_BYTES, STATE_KIND, STATE_SCHEMA_VERSION, State, StateCounts, StateError, StateFormat,
    StateHeader, StateLimits, decode_state, encode_state, read_state_file, write_state_file,
};
pub use timestamp::{TsFormat, epoch_float_to_micros, epoch_int_to_micros, parse_iso};
