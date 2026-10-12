//! The parameter extractor of Python: compiled masks and delimiters that serve any number of messages.
//!
//! The class only converts. The alignment of a message with a template lives in `logfold_core::extract_parameters`.

use logfold_core::{Fit, RuleMasker, Tokenizer, extract_parameters};
use logfold_engine::EngineError;
use pyo3::prelude::*;

use crate::convert::parse_masks;
use crate::translate;

/// One parameter as Python gets it: the position of the token in the template, the name and the value.
type Row = (usize, String, String);

/// The compiled masks and delimiters of a mining configuration.
#[pyclass(frozen, module = "logfold._core")]
pub(crate) struct NativeExtractor {
    masker: RuleMasker,
    tokenizer: Tokenizer,
}

#[pymethods]
impl NativeExtractor {
    /// Compiles `masks` (a list of dicts with `name`, `pattern`, `token` and `ascii`) and the ASCII `delimiters`.
    #[new]
    fn new(masks: &Bound<'_, PyAny>, delimiters: &str) -> PyResult<Self> {
        let rules = parse_masks(masks)?;
        let masker = RuleMasker::new(&rules).map_err(|error| translate(EngineError::Core(error)))?;
        let tokenizer = Tokenizer::new(delimiters.as_bytes()).map_err(|error| translate(EngineError::Core(error)))?;
        Ok(NativeExtractor { masker, tokenizer })
    }

    /// Gives, for every message, the parameters at the variable positions of `template` (its text, with its tokens
    /// joined by single spaces), or `None` for a message that does not fit it.
    fn extract(&self, py: Python<'_>, template: &str, messages: Vec<String>) -> Vec<Option<Vec<Row>>> {
        let tokens: Vec<&[u8]> =
            if template.is_empty() { Vec::new() } else { template.split(' ').map(str::as_bytes).collect() };
        py.detach(|| {
            messages
                .iter()
                .map(|message| {
                    extract_parameters(&self.masker, &self.tokenizer, &tokens, message.as_bytes(), Fit::Exact).map(
                        |parameters| {
                            parameters
                                .into_iter()
                                .map(|p| (p.position, p.name, String::from_utf8_lossy(&p.value).into_owned()))
                                .collect()
                        },
                    )
                })
                .collect()
        })
    }
}
