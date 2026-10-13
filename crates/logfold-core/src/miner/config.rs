//! The parameters of the template tree.

use crate::error::CoreError;

/// Parameters of the template tree.
#[derive(Clone, Debug)]
pub struct MinerConfig {
    pub(super) depth: usize,
    pub(super) max_children: usize,
    pub(super) max_templates: usize,
    pub(super) threshold_micro: u64,
}

impl MinerConfig {
    /// Validates and builds a configuration (see `docs/ALGORITHM.md` §4).
    pub fn new(depth: usize, sim_th: f64, max_children: usize, max_templates: usize) -> Result<Self, CoreError> {
        if depth < 3 {
            return Err(CoreError::InvalidConfig("depth must be at least 3".into()));
        }
        if !(0.0..=1.0).contains(&sim_th) {
            return Err(CoreError::InvalidConfig("sim_th must be within [0, 1]".into()));
        }
        if max_children < 1 {
            return Err(CoreError::InvalidConfig("max_children must be at least 1".into()));
        }
        if max_templates < 1 {
            return Err(CoreError::InvalidConfig("max_templates must be at least 1".into()));
        }
        let threshold_micro = (sim_th * 1_000_000.0 + 0.5).floor() as u64;
        Ok(MinerConfig { depth, max_children, max_templates, threshold_micro })
    }

    pub(super) fn token_layers(&self, n: usize) -> usize {
        if n == 0 { 0 } else { (self.depth - 3).min(n - 1) }
    }
}

impl Default for MinerConfig {
    fn default() -> Self {
        MinerConfig { depth: 4, max_children: 100, max_templates: 100_000, threshold_micro: 400_000 }
    }
}
