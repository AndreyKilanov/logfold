//! Conversion of the data of a report from Python into the rows of `logfold_report`.
//!
//! Python hands over the columns of a result once. The texts are read in place, as `&str` borrowed from the Python
//! strings, so a column of a hundred thousand templates is not copied; the report is rendered while the GIL is held.

use logfold_core::Level;
use logfold_report::{Analysis, Diff, Row, Run, Subject};
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString};

use crate::CoreConfigError;
use crate::convert::{optional, required, sub_dict};

/// A column of strings; `None` stands for a Python `None`.
type Strings<'py> = Vec<Option<Bound<'py, PyString>>>;

fn strings<'py>(list: &Bound<'py, PyAny>) -> PyResult<Strings<'py>> {
    let list = list.cast::<PyList>()?;
    let mut column = Vec::with_capacity(list.len());
    for item in list.iter() {
        column.push(if item.is_none() { None } else { Some(item.cast_into::<PyString>()?) });
    }
    Ok(column)
}

/// The columns of a list of templates; a column that Python did not send is empty and reads as the default.
struct Columns<'py> {
    count: usize,
    ids: Strings<'py>,
    texts: Strings<'py>,
    levels: Strings<'py>,
    before: Vec<u64>,
    after: Vec<u64>,
    ratios: Vec<Option<f64>>,
    first: Strings<'py>,
    last: Strings<'py>,
}

fn check(name: &str, length: usize, count: usize) -> PyResult<()> {
    if length != 0 && length != count {
        return Err(CoreConfigError::new_err(format!("the column '{name}' has {length} items, expected {count}")));
    }
    Ok(())
}

fn text_column<'py>(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Strings<'py>> {
    optional(dict, key)?.map_or_else(|| Ok(Vec::new()), |value| strings(&value))
}

/// The canonical level name of `level`, or `None` when it is not one: a level that does not come from logfold carries
/// no markup into a report.
fn canonical(level: &str) -> Option<&'static str> {
    Level::NAMES.iter().find(|name| **name == level).copied()
}

fn cell<'a>(column: &'a Strings<'_>, index: usize) -> PyResult<&'a str> {
    match column.get(index) {
        Some(Some(value)) => value.to_str(),
        _ => Ok(""),
    }
}

impl<'py> Columns<'py> {
    fn parse(dict: &Bound<'py, PyDict>) -> PyResult<Self> {
        let texts = strings(&required(dict, "texts")?)?;
        let columns = Columns {
            count: texts.len(),
            ids: text_column(dict, "ids")?,
            texts,
            levels: text_column(dict, "levels")?,
            before: optional(dict, "before")?.map(|value| value.extract()).transpose()?.unwrap_or_default(),
            after: optional(dict, "after")?.map(|value| value.extract()).transpose()?.unwrap_or_default(),
            ratios: optional(dict, "ratios")?.map(|value| value.extract()).transpose()?.unwrap_or_default(),
            first: text_column(dict, "first")?,
            last: text_column(dict, "last")?,
        };
        let count = columns.count;
        check("ids", columns.ids.len(), count)?;
        check("levels", columns.levels.len(), count)?;
        check("before", columns.before.len(), count)?;
        check("after", columns.after.len(), count)?;
        check("ratios", columns.ratios.len(), count)?;
        check("first", columns.first.len(), count)?;
        check("last", columns.last.len(), count)?;
        Ok(columns)
    }

    fn rows(&self) -> PyResult<Vec<Row<'_>>> {
        let mut rows = Vec::with_capacity(self.count);
        for index in 0..self.count {
            let level = match self.levels.get(index) {
                Some(Some(value)) => canonical(value.to_str()?),
                _ => None,
            };
            rows.push(Row {
                id: cell(&self.ids, index)?,
                text: cell(&self.texts, index)?,
                level,
                before: self.before.get(index).copied().unwrap_or(0),
                after: self.after.get(index).copied().unwrap_or(0),
                ratio: self.ratios.get(index).copied().flatten(),
                first_seen: cell(&self.first, index)?,
                last_seen: cell(&self.last, index)?,
            });
        }
        Ok(rows)
    }
}

/// The name, records and unparsed lines of a run.
struct RunData<'py> {
    name: Bound<'py, PyString>,
    records: u64,
    unparsed: u64,
}

impl<'py> RunData<'py> {
    fn parse(dict: &Bound<'py, PyDict>, key: &str) -> PyResult<Self> {
        let run = sub_dict(dict, key)?;
        Ok(Self {
            name: required(&run, "name")?.cast_into::<PyString>()?,
            records: required(&run, "records")?.extract()?,
            unparsed: optional(&run, "unparsed")?.map(|value| value.extract()).transpose()?.unwrap_or(0),
        })
    }

    fn view(&self) -> PyResult<Run<'_>> {
        Ok(Run { name: self.name.to_str()?, records: self.records, unparsed: self.unparsed })
    }
}

fn number(options: &Bound<'_, PyDict>, key: &str) -> PyResult<usize> {
    required(options, key)?.extract()
}

fn warnings(data: &Bound<'_, PyDict>) -> PyResult<Vec<String>> {
    Ok(optional(data, "warnings")?.map(|value| value.extract()).transpose()?.unwrap_or_default())
}

/// Renders the report `name` of a result given as columns; see `docs/ALGORITHM.md` section 12.
pub(crate) fn render(name: &str, data: &Bound<'_, PyDict>, options: &Bound<'_, PyDict>) -> PyResult<String> {
    let top = number(options, "top")?;
    let limit = match name {
        "github-summary" => number(options, "max_bytes")?,
        "chat-message" => number(options, "max_chars")?,
        "junit" | "prometheus" => 0,
        other => return Err(CoreConfigError::new_err(format!("unknown report {other:?}"))),
    };
    let kind: String = required(data, "kind")?.extract()?;
    let warnings = warnings(data)?;
    let warnings: Vec<&str> = warnings.iter().map(String::as_str).collect();
    match kind.as_str() {
        "analysis" => render_analysis(name, data, &warnings, top, limit),
        "diff" => render_diff(name, data, &warnings, top, limit),
        other => Err(CoreConfigError::new_err(format!("unknown kind of result {other:?}"))),
    }
}

fn render_analysis(
    name: &str,
    data: &Bound<'_, PyDict>,
    warnings: &[&str],
    top: usize,
    limit: usize,
) -> PyResult<String> {
    let run = RunData::parse(data, "run")?;
    let columns = Columns::parse(&sub_dict(data, "templates")?)?;
    let levels: Vec<(String, u64)> = required(data, "levels")?.extract()?;
    let levels: Vec<(&str, u64)> = levels.iter().map(|(name, count)| (name.as_str(), *count)).collect();
    let rows = columns.rows()?;
    let analysis = Analysis { run: run.view()?, templates: &rows, levels: &levels, warnings };
    match name {
        "github-summary" => Ok(logfold_report::github_summary(&Subject::Analysis(analysis), top, limit)),
        "chat-message" => Ok(logfold_report::chat_message(&Subject::Analysis(analysis), top, limit)),
        "prometheus" => Ok(logfold_report::prometheus(&Subject::Analysis(analysis), top)),
        _ => Err(CoreConfigError::new_err(format!("the {name} report renders diff results"))),
    }
}

fn render_diff(name: &str, data: &Bound<'_, PyDict>, warnings: &[&str], top: usize, limit: usize) -> PyResult<String> {
    let (before, after) = (RunData::parse(data, "before")?, RunData::parse(data, "after")?);
    let new = Columns::parse(&sub_dict(data, "new")?)?;
    let changed = Columns::parse(&sub_dict(data, "changed")?)?;
    let disappeared = Columns::parse(&sub_dict(data, "disappeared")?)?;
    let (new, changed, disappeared) = (new.rows()?, changed.rows()?, disappeared.rows()?);
    let diff = Diff {
        before: before.view()?,
        after: after.view()?,
        new: &new,
        changed: &changed,
        disappeared: &disappeared,
        unchanged: required(data, "unchanged")?.extract()?,
        warnings,
    };
    match name {
        "github-summary" => Ok(logfold_report::github_summary(&Subject::Diff(diff), top, limit)),
        "chat-message" => Ok(logfold_report::chat_message(&Subject::Diff(diff), top, limit)),
        "prometheus" => Ok(logfold_report::prometheus(&Subject::Diff(diff), top)),
        _ => Ok(logfold_report::junit(&diff, top)),
    }
}
