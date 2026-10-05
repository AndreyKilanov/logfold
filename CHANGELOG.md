# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/). Before 1.0, breaking changes may land in a minor release.

## [Unreleased]

### Added

- `--report NAME` on `logfold analyze` and `logfold diff` chooses the reporter by name, so plugin reporters work from
  the command line: with `--out` it writes the file, without `--out` its text is printed instead of the tables. The
  `--out` suffix `.csv` selects the `csv` reporter. An unknown or unsuitable reporter and a bad `--out` suffix now fail
  before the logs are read.
- Compare saved results without the logs: `logfold.load_analysis(path)` loads a JSON report of `analyze`, and
  `logfold.diff()` accepts two `AnalysisResult` objects. `logfold diff before.json after.json` detects saved reports
  by their header. The results are mined separately and are not re-counted, so templates are joined by id and the
  matcher pairs the rest; a warning says so, and another one is added when the masks, parameters or formats differ.
  Results of different algorithm versions are rejected. Examples are kept as saved, so `--examples masked` is refused for
  saved results. Reports must be UTF-8 (a BOM is accepted), at most 256 MiB, with template ids matching their text.

### Fixed

- Terminal output no longer acts on control characters from log content: in the tables and in `--report` printed to a
  terminal an escape sequence (retitle the window, hide text, write to the clipboard) is shown as a visible `\xNN`
  instead. Files and pipes keep the raw text.
- A plugin reporter that raises or returns something other than text fails with `error: reporter 'NAME' failed: ...` and
  exit code 1 instead of a traceback.

### Changed

- Plugin discovery reads the installed package metadata once instead of three times, so every command that
  resolves a format or a reporter starts about 9 ms faster (307 ms instead of 316 ms for `logfold analyze` on a small
  file, median of 25 runs). The output is unchanged.
- `--out report.md` now writes Markdown tables (the `markdown` reporter) instead of the plain text report; use
  `--out report.txt` or `--report text` for the old output.
- `analyze --min-count N --out result.json` now writes every template to the JSON file (the option still hides rare
  templates from tables and from other report formats), so the file can be compared later with `diff`.

## [0.2.1] - 2026-10-04

### Changed

- Faster mining when many templates share one leaf of the template tree, for example raw Thunderbird lines read with the
  `plain` format (the first token is a constant dash): 886 MB with one thread takes 6 s instead of 67 s without masks and
  7 s instead of 29 s with masks. The index lists of the tokens that most templates share are no longer walked. The output
  is identical (same templates, counts, timestamps, levels and examples), so `ALGO_VERSION` and the algorithm
  specification are unchanged.
- Faster value masking with the default rules: the scanner examines only the positions that can start a match (hex letters
  and digits inside words can only start a uuid or a timestamp, which have a dash at a fixed distance). 400 MB of HDFS
  logs are masked in 0.7 s instead of 1.45 s, and 1.57 GB of HDFS needs 7.8 s instead of 10.6 s with one thread. The
  masked text, and therefore the output, is identical.
- The command line starts about 20 ms faster (285 ms instead of 305 ms for `logfold --version`): the plugin catalog, and
  with it `urllib`, `http` and `ssl`, is imported only by the `logfold plugins` commands.

## [0.2.0] - 2026-10-04

### Added

- Default plugins inside `pip install logfold`: formats `logfmt` and `serilog-clef`, reporters `markdown` and `csv`
  (CSV cells that a spreadsheet would read as a formula are neutralized), diff matcher `jaccard`.
- `logfold plugins list|check|install`: list every format, reporter and matcher with its source, show the plugins of a
  catalog that are not installed yet, and install one with pip after confirmation. The catalog is bundled and works
  offline; `--online` fetches the latest one over HTTPS, `--catalog` takes a file or an HTTPS URL, and
  `LOGFOLD_OFFLINE=1` forbids network access.
- Plugins from your own folder, without packaging: a `.py` file or package in the plugin folder (`%APPDATA%\logfold\plugins`,
  `~/.config/logfold/plugins`), in `LOGFOLD_PLUGIN_PATH` or given with `--plugins-dir` provides `FORMATS`, `REPORTERS` and
  `MATCHERS`. `logfold plugins dir` shows the folder, `logfold plugins new KIND NAME` writes a working template there.
  Nothing is loaded from the current directory; world-writable or foreign files are skipped on POSIX;
  `LOGFOLD_NO_USER_PLUGINS=1` switches the implicit folders off.
- `logfold.ext.plugin_sources()`, `add_plugin_directory()`, `plugin_directories()` and `default_plugin_dir()`.
- Plugins guide (`docs/plugins.md`) and an example plugin package (`examples/logfold-example-plugin`).

### Fixed

- HTML reports: the headers of numeric columns are right-aligned like their values.

### Changed

- `diff` shows the engine and the elapsed time in seconds in the console summary, the text report and the HTML report,
  like `analyze` does.

## [0.1.0] - 2026-10-04

### Added

- `logfold.analyze()` and `logfold.diff()`; `logfold analyze`, `logfold diff`, `logfold formats`, `logfold info`.
- Rust core with a Drain-compatible miner, one-pass value masking, sequential and deterministic parallel (chunked)
  execution, and a two-phase `diff` that assigns every record to the finished template tree.
- Pure-Python reference engine that gives identical results to the native sequential strategy.
- Built-in formats (plain, jsonl, journald, nginx, apache, nginx-error, syslog, k8s, app) with auto-detection and
  indented-continuation (multiline) detection; `regex:<pattern>` formats.
- Entry-point plugins for formats, reporters and diff matchers.
- JSON (versioned schemas in `docs/schema`), self-contained HTML and plain-text reports.
- `--high-cardinality` / `high_cardinality=True`: bounded, fast mode for data with a huge number of distinct messages.
- Benchmark and quality harnesses (`bench/`, `eval/`).
