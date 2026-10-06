use std::path::PathBuf;

use logfold_core::{FrozenTemplate, Level, MaskRule};
use logfold_engine::{MineOutput, MineRequest, MiningParams, Strategy, DEFAULT_CHUNK_BYTES};
use logfold_io::{FormatConfig, FormatSpec, TimeWindow};
use pyo3::exceptions::PyKeyError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList};

use crate::CoreConfigError;

fn required<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyAny>> {
    dict.get_item(key)?.ok_or_else(|| PyKeyError::new_err(format!("missing request key '{key}'")))
}

fn optional<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Option<Bound<'py, PyAny>>> {
    Ok(dict.get_item(key)?.filter(|value| !value.is_none()))
}

fn optional_string(dict: &Bound<'_, PyDict>, key: &str) -> PyResult<Option<String>> {
    optional(dict, key)?.map(|value| value.extract::<String>()).transpose()
}

fn sub_dict<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Bound<'py, PyDict>> {
    Ok(required(dict, key)?.cast_into::<PyDict>()?)
}

fn parse_format(dict: &Bound<'_, PyDict>) -> PyResult<FormatConfig> {
    let kind: String = required(dict, "kind")?.extract()?;
    let spec = match kind.as_str() {
        "plain" => FormatSpec::Plain { record_start: optional_string(dict, "record_start")? },
        "json" => FormatSpec::Json {
            message_keys: required(dict, "message_keys")?.extract()?,
            time_keys: required(dict, "time_keys")?.extract()?,
            level_keys: required(dict, "level_keys")?.extract()?,
        },
        "regex" => FormatSpec::Regex {
            pattern: required(dict, "pattern")?.extract()?,
            message_group: optional_string(dict, "message_group")?,
            time_group: optional_string(dict, "time_group")?,
            level_group: optional_string(dict, "level_group")?,
        },
        other => return Err(CoreConfigError::new_err(format!("unknown format kind '{other}'"))),
    };
    Ok(FormatConfig {
        spec,
        ts_format: optional_string(dict, "ts_format")?,
        multiline: required(dict, "multiline")?.extract()?,
    })
}

fn parse_masks(list: &Bound<'_, PyAny>) -> PyResult<Vec<MaskRule>> {
    let mut rules = Vec::new();
    for item in list.try_iter()? {
        let item = item?.cast_into::<PyDict>()?;
        rules.push(MaskRule {
            name: required(&item, "name")?.extract()?,
            pattern: required(&item, "pattern")?.extract()?,
            token: required(&item, "token")?.extract()?,
            ascii: required(&item, "ascii")?.extract()?,
        });
    }
    Ok(rules)
}

fn parse_mining(dict: &Bound<'_, PyDict>) -> PyResult<MiningParams> {
    let delimiters: String = required(dict, "delimiters")?.extract()?;
    Ok(MiningParams {
        depth: required(dict, "depth")?.extract()?,
        sim_th: required(dict, "sim_th")?.extract()?,
        max_children: required(dict, "max_children")?.extract()?,
        max_templates: required(dict, "max_templates")?.extract()?,
        delimiters: delimiters.into_bytes(),
    })
}

fn parse_warm_start(dict: &Bound<'_, PyDict>) -> PyResult<bool> {
    Ok(match optional(dict, "warm_start")? {
        Some(value) => value.extract::<bool>()?,
        None => false,
    })
}

fn parse_strategy(dict: &Bound<'_, PyDict>) -> PyResult<Strategy> {
    let name: String = required(dict, "strategy")?.extract()?;
    match name.as_str() {
        "sequential" => Ok(Strategy::Sequential),
        "chunked" | "adaptive" => {
            let chunk_bytes = match optional(dict, "chunk_bytes")? {
                Some(value) => value.extract::<u64>()?,
                None => DEFAULT_CHUNK_BYTES,
            };
            let threads = match optional(dict, "threads")? {
                Some(value) => value.extract::<usize>()?,
                None => std::thread::available_parallelism().map_or(1, |n| n.get()),
            };
            Ok(if name == "adaptive" {
                Strategy::Adaptive { chunk_bytes, threads }
            } else {
                Strategy::Chunked { chunk_bytes, threads }
            })
        }
        other => Err(CoreConfigError::new_err(format!("unknown strategy '{other}'"))),
    }
}

fn parse_windows(dict: &Bound<'_, PyDict>) -> PyResult<Vec<TimeWindow>> {
    let Some(value) = optional(dict, "windows")? else { return Ok(Vec::new()) };
    let bounds: Vec<(Option<i64>, Option<i64>)> = value.extract()?;
    Ok(bounds.into_iter().map(|(since, until)| TimeWindow { since, until }).collect())
}

/// Converts the plain-data request dict into an engine request.
pub(crate) fn parse_request(dict: &Bound<'_, PyDict>) -> PyResult<MineRequest> {
    let runs: Vec<Vec<String>> = required(dict, "runs")?.extract()?;
    Ok(MineRequest {
        runs: runs.into_iter().map(|files| files.into_iter().map(PathBuf::from).collect()).collect(),
        windows: parse_windows(dict)?,
        format: parse_format(&sub_dict(dict, "format")?)?,
        masks: parse_masks(&required(dict, "masks")?)?,
        mining: parse_mining(&sub_dict(dict, "mining")?)?,
        strategy: parse_strategy(&sub_dict(dict, "execution")?)?,
        warm_start: parse_warm_start(&sub_dict(dict, "execution")?)?,
        recount: required(dict, "recount")?.extract()?,
    })
}

/// Per-run statistics of every template as parallel lists.
///
/// Building the Python objects here, once per column, is much cheaper than one dictionary per template and run; the
/// Python side zips the columns when it needs a row.
fn run_columns<'py>(py: Python<'py>, templates: &[FrozenTemplate], run: usize) -> PyResult<Bound<'py, PyDict>> {
    let counts = PyList::empty(py);
    let first = PyList::empty(py);
    let last = PyList::empty(py);
    let levels = PyList::empty(py);
    let level = PyList::empty(py);
    let examples = PyList::empty(py);
    for frozen in templates {
        let stats = &frozen.runs[run];
        counts.append(stats.count)?;
        if stats.has_time() {
            first.append(stats.first)?;
            last.append(stats.last)?;
        } else {
            first.append(py.None())?;
            last.append(py.None())?;
        }
        let present = PyDict::new(py);
        let mut most_severe: Option<&str> = None;
        for (rank, value) in stats.levels.iter().enumerate() {
            if *value > 0 {
                present.set_item(Level::NAMES[rank], *value)?;
                most_severe = Some(Level::NAMES[rank]);
            }
        }
        levels.append(present)?;
        level.append(most_severe)?;
        match &stats.example {
            Some(bytes) => examples.append(String::from_utf8_lossy(bytes).as_ref())?,
            None => examples.append(py.None())?,
        }
    }
    let item = PyDict::new(py);
    item.set_item("counts", counts)?;
    item.set_item("first", first)?;
    item.set_item("last", last)?;
    item.set_item("levels", levels)?;
    item.set_item("level", level)?;
    item.set_item("examples", examples)?;
    Ok(item)
}

fn template_columns<'py>(py: Python<'py>, output: &MineOutput) -> PyResult<Bound<'py, PyDict>> {
    let columns = PyDict::new(py);
    let ids = PyList::empty(py);
    let texts = PyList::empty(py);
    for frozen in &output.templates {
        ids.append(&frozen.id)?;
        texts.append(&frozen.text)?;
    }
    columns.set_item("ids", ids)?;
    columns.set_item("texts", texts)?;
    let runs = PyList::empty(py);
    for run in 0..output.runs.len() {
        runs.append(run_columns(py, &output.templates, run)?)?;
    }
    columns.set_item("runs", runs)?;
    Ok(columns)
}

/// Converts the engine output into plain Python containers.
pub(crate) fn build_output<'py>(py: Python<'py>, output: &MineOutput) -> PyResult<Bound<'py, PyDict>> {
    let result = PyDict::new(py);
    let runs = PyList::empty(py);
    for run in &output.runs {
        let item = PyDict::new(py);
        item.set_item("files", run.files)?;
        item.set_item("lines", run.lines)?;
        item.set_item("records", run.records)?;
        item.set_item("unparsed", run.unparsed)?;
        item.set_item("out_of_range", run.out_of_range)?;
        item.set_item("untimed", run.untimed)?;
        item.set_item("bytes", run.bytes)?;
        item.set_item("tz_aware", run.tz_aware)?;
        item.set_item("overflowed", run.overflowed)?;
        runs.append(item)?;
    }
    result.set_item("runs", runs)?;
    result.set_item("templates", template_columns(py, output)?)?;
    let metrics = PyDict::new(py);
    metrics.set_item("engine", "native")?;
    metrics.set_item("strategy", output.metrics.strategy)?;
    metrics.set_item("threads", output.metrics.threads)?;
    metrics.set_item("chunks", output.metrics.chunks)?;
    metrics.set_item("wall_total_s", output.metrics.wall_total_s)?;
    metrics.set_item("wall_mine_s", output.metrics.wall_mine_s)?;
    metrics.set_item("wall_merge_s", output.metrics.wall_merge_s)?;
    metrics.set_item("wall_recount_s", output.metrics.wall_recount_s)?;
    metrics.set_item("wall_freeze_s", output.metrics.wall_freeze_s)?;
    result.set_item("metrics", metrics)?;
    result.set_item("level_names", Level::NAMES.to_vec())?;
    Ok(result)
}
