use std::fs::File;
use std::io::{BufReader, Read, Seek, SeekFrom};
use std::path::Path;

use crate::error::IoError;

/// Path that selects standard input.
pub const STDIN_PATH: &str = "-";

/// Compression of a byte source, detected from magic bytes.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Compression {
    /// Plain bytes; the source is seekable and can be split into chunks.
    None,
    /// gzip (possibly several members).
    Gzip,
    /// Zstandard.
    Zstd,
    /// Standard input (not seekable).
    Stdin,
}

/// Facts about a source needed for planning.
#[derive(Clone, Copy, Debug)]
pub struct SourceInfo {
    /// Detected compression.
    pub compression: Compression,
    /// Size in bytes of the file on disk (0 for stdin).
    pub size: u64,
}

impl SourceInfo {
    /// True when the source can be read from an arbitrary byte offset.
    pub fn seekable(&self) -> bool {
        self.compression == Compression::None
    }
}

fn read_error(path: &Path, source: std::io::Error) -> IoError {
    IoError::Read { path: path.to_path_buf(), source }
}

/// Inspects `path`: compression and size.
pub fn inspect(path: &Path) -> Result<SourceInfo, IoError> {
    if path.as_os_str() == STDIN_PATH {
        return Ok(SourceInfo { compression: Compression::Stdin, size: 0 });
    }
    let mut file = File::open(path).map_err(|e| read_error(path, e))?;
    let size = file.metadata().map_err(|e| read_error(path, e))?.len();
    let mut magic = [0u8; 4];
    let mut filled = 0;
    while filled < magic.len() {
        let Some(unfilled) = magic.get_mut(filled..) else { break };
        match file.read(unfilled).map_err(|e| read_error(path, e))? {
            0 => break,
            n => filled += n,
        }
    }
    let compression = if filled >= 2 && magic[..2] == [0x1f, 0x8b] {
        Compression::Gzip
    } else if filled >= 4 && magic == [0x28, 0xb5, 0x2f, 0xfd] {
        Compression::Zstd
    } else {
        Compression::None
    };
    Ok(SourceInfo { compression, size })
}

/// Opens `path` for reading. Plain files start at `offset`; compressed sources and stdin require `offset == 0`.
pub fn open_source(path: &Path, info: &SourceInfo, offset: u64) -> Result<Box<dyn Read + Send>, IoError> {
    match info.compression {
        Compression::Stdin => Ok(Box::new(std::io::stdin())),
        Compression::None => {
            let mut file = File::open(path).map_err(|e| read_error(path, e))?;
            if offset > 0 {
                file.seek(SeekFrom::Start(offset)).map_err(|e| read_error(path, e))?;
            }
            Ok(Box::new(file))
        }
        Compression::Gzip => {
            let file = File::open(path).map_err(|e| read_error(path, e))?;
            Ok(Box::new(flate2::read::MultiGzDecoder::new(BufReader::with_capacity(1 << 20, file))))
        }
        Compression::Zstd => open_zstd(path),
    }
}

#[cfg(feature = "zstd")]
fn open_zstd(path: &Path) -> Result<Box<dyn Read + Send>, IoError> {
    let file = File::open(path).map_err(|e| read_error(path, e))?;
    let decoder = zstd::stream::read::Decoder::new(file).map_err(|e| read_error(path, e))?;
    Ok(Box::new(decoder))
}

#[cfg(not(feature = "zstd"))]
fn open_zstd(path: &Path) -> Result<Box<dyn Read + Send>, IoError> {
    Err(IoError::Format(format!("'{}' is zstd-compressed but zstd support is not built in", path.display())))
}
