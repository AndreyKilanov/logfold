use std::sync::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};

use logfold_engine::Observer;
use pyo3::prelude::*;

/// Bridges engine progress and cancellation to Python: calls the optional callback and polls for Ctrl+C.
pub(crate) struct PyObserver {
    callback: Option<Py<PyAny>>,
    stop: AtomicBool,
    error: Mutex<Option<PyErr>>,
}

impl PyObserver {
    pub(crate) fn new(callback: Option<Py<PyAny>>) -> Self {
        PyObserver { callback, stop: AtomicBool::new(false), error: Mutex::new(None) }
    }

    pub(crate) fn take_error(&self) -> Option<PyErr> {
        self.error.lock().ok().and_then(|mut slot| slot.take())
    }

    fn record(&self, error: PyErr) {
        if let Ok(mut slot) = self.error.lock() {
            slot.get_or_insert(error);
        }
        self.stop.store(true, Ordering::Relaxed);
    }
}

impl Observer for PyObserver {
    fn on_bytes(&self, consumed: u64) {
        let Some(callback) = &self.callback else { return };
        Python::attach(|py| {
            if let Err(error) = callback.call1(py, (consumed,)) {
                self.record(error);
            }
        });
    }

    fn cancelled(&self) -> bool {
        if self.stop.load(Ordering::Relaxed) {
            return true;
        }
        Python::attach(|py| {
            if let Err(error) = py.check_signals() {
                self.record(error);
            }
        });
        self.stop.load(Ordering::Relaxed)
    }
}
