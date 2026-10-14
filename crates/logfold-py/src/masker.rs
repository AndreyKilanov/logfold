//! The masker of Python: compiled masking rules that serve any number of texts.
//!
//! The class only converts. The rules are applied by `logfold_core::RuleMasker`, whose regex engine runs in time linear in
//! the text, whatever the patterns of a set file are.

use logfold_core::{MaskScratch, RuleMasker};
use logfold_engine::EngineError;
use pyo3::prelude::*;

use crate::convert::parse_masks;
use crate::translate;

/// The compiled masking rules of a mining configuration.
#[pyclass(frozen, module = "logfold._core")]
pub(crate) struct NativeMasker {
    masker: RuleMasker,
}

#[pymethods]
impl NativeMasker {
    /// Compiles `masks`, a list of dicts with `name`, `pattern`, `token`, `ascii` and `check`.
    #[new]
    fn new(masks: &Bound<'_, PyAny>) -> PyResult<Self> {
        let rules = parse_masks(masks)?;
        let masker = RuleMasker::new(&rules).map_err(|error| translate(EngineError::Core(error)))?;
        Ok(NativeMasker { masker })
    }

    /// Tells whether the first layer is gated: whether a text without the literals of its rules skips the regex engine.
    fn first_layer_is_gated(&self) -> bool {
        self.masker.first_layer_is_gated()
    }

    /// Returns each text with the rules applied.
    fn mask_many(&self, py: Python<'_>, texts: Vec<String>) -> Vec<String> {
        py.detach(|| {
            let mut scratch = MaskScratch::default();
            texts
                .iter()
                .map(|text| String::from_utf8_lossy(self.masker.mask(text.as_bytes(), &mut scratch)).into_owned())
                .collect()
        })
    }
}
