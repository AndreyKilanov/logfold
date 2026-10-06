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
mod timestamp;

pub use error::IoError;
pub use format::{CompiledFormat, FormatConfig, FormatSpec, ParsedRecord};
pub use lines::{INITIAL_WINDOW, Line, LineReader};
pub use records::{Counters, Placement, ScanOutcome, ScanWindow, TICK_BYTES, TimeWindow, scan_records};
pub use source::{Compression, STDIN_PATH, SourceInfo, inspect, open_source};
pub use timestamp::{TsFormat, epoch_float_to_micros, epoch_int_to_micros, parse_iso};
