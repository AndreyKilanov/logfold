# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/). Before 1.0, breaking changes may land in a minor release.

## [Unreleased]

### Changed

- Python 3.11 or newer is required; Python 3.10 is no longer supported (0.4.0 is the last release for it). The wheels are
  tagged `cp311-abi3`.

## [0.4.0] - 2026-10-07

### Added

- Default format plugins `haproxy`, `postgresql`, `postgresql-csv`, `docker-json`, `github-actions` and `log4j`, and
  `--format "log4j:<pattern>"` (library: `log4j_format()` in `logfold.ext`) for any log4j or logback pattern.
- Default reporters for pipelines: `github-summary` (job summary Markdown), `junit` (`.xml`, a new WARN+ template fails a
  test), `chat-message` (Slack, Mattermost, Telegram text) and `prometheus` (`.prom`, textfile collector gauges); written
  by the Rust core for large listings, extension contract version 7.
- Diff matchers `jaccard-idf` (rare words count more), `overlap` (an extended message) and `rules:FILE` (pairs from your
  file), computed by the Rust core; extension contract version 6.
- `--append` for `--out` on `analyze` and `diff` (and `save(append=True)`) adds a text or Markdown report to a file, for
  `$GITHUB_STEP_SUMMARY`; new page `docs/ci.md` with GitHub Actions and GitLab CI recipes.
- `diff` with several baselines: `--baseline FILE` (repeatable) and `--min-baselines N`; a template is new only if no
  baseline has it (library: `baselines`, `min_baselines`).
- Time windows: `--since`/`--until` on `analyze` and `diff`, and `diff LOG --split-at TIME` to compare the part of one log
  before a time with the part after it (library: `since`, `until`, `split_at`); extension contract version 5.
- Plugin names: an unknown format, reporter or matcher gets a hint with the catalog's install command or the closest name;
  `formats` and `--help` list the available plugins; `min_logfold` in the catalog and `plugins install` refuses a plugin
  that needs a newer logfold. Library: `unknown_name_hint()`, `write_template()`.
- `logfold plugins list` shows built-in, installed and catalog plugins with a status (`--installed`, `--available`, `--kind`),
  `plugins info NAME` describes one; library: `list_plugins()`, `plugin_info()`, `closest()`. `plugins install` falls back to
  `uv pip install`; `plugins list --json` rows gained fields.
- `logfold inspect FILE`: the detected format, the first records as parsed, and the levels, time range and unparsed lines
  of a sample of the file.
- `--level` and `--only-alerts` on `analyze` and `diff`; in `diff` the filter also applies to the `--fail-on-new*` gates.
- Errors carry a next step: `LogfoldError.hint`, a `hint:` line in the CLI, and "did you mean" for a misspelled format,
  reporter or matcher (new subclasses of `FormatError` and `ConfigError` in `logfold.errors`).
- `--help` of `analyze` and `diff` groups the options into panels and ends with examples.
- Library: `AnalysisResult.filter()`, `DiffResult.filter()`, `AnalysisResult.levels`, `result.save(path)` (reporter by suffix),
  `logfold.inspect_file()`, `logfold.info()`, `logfold.is_saved_analysis()`, and `logfold.ext.printable()`.
- `result.warnings` says when `warm_start` or `chunk_bytes` was ignored because the run was sequential. The python engine's
  `warm_start` warning moved there from the log.

### Changed

- Building from source needs Rust 1.99 or newer (it was 1.80); the Rust code is on edition 2024.
- `diff`: a template is `changed` only if a G-test finds the change unlikely to be noise (`--significance`, default 0.01;
  `--significance 1` restores the previous result); `changed` is sorted by the new `score`, and `score` and `p_value` are
  in the JSON, CSV and terminal output. New and disappeared templates and the gates are not affected.
- HTML report: the summary cards of `analyze` and `diff` are two rows of five, the counts of new, WARN+, disappeared and
  changed templates and of unparsed lines have their own colors, and the columns of all tables line up.
- Error messages are shorter: the system's localized text is not repeated and markup in a path is printed literally.
- Terminal output: a `levels:` line, "N more templates (X% of records)", a hint to open a written HTML report, and the
  transfer speed in progress.

### Fixed

- HTML report: the share bars of `analyze` were blocked by the Content-Security-Policy and never shown.
- An unwritable `--out` file is an error, not a traceback; paths in errors are not wrapped or shown with doubled
  backslashes on Windows.

### Security

- No built-in reporter returns a raw control character from a log (terminal escape sequences): they are shown as hex
  escapes (`json` uses unicode escapes). Values on the result objects stay raw.
- Format detection reads a bounded sample (lines cut at 1 MiB, 8 MiB in total), so a huge single-line file or a gzip bomb
  no longer allocates memory in proportion to its size.
- Memory no longer grows with the size of one line or one record: a line keeps at most its first 16 MiB and a multi-line
  record takes lines only while it is smaller than 1 MiB (`docs/ALGORITHM.md` section 1.1). A 400 MB record took 2.6 GB
  and 11 s, it now takes 45 MB and under a second; a file of one line without a line feed took 4 to 5 times its size.

## [0.3.0] - 2026-10-05

### Added

- Compare saved results without the logs: `logfold.load_analysis(path)` loads a JSON report of `analyze`, `logfold.diff()`
  accepts two `AnalysisResult` objects, and `logfold diff before.json after.json` detects saved reports by their header.
  Templates are joined by id and the matcher pairs the rest. The results are mined separately and are not re-counted, and a
  warning says so (and when the masks, parameters or formats differ). Reports of different algorithm versions are refused,
  `--examples masked` is refused for saved results, and a report must be UTF-8, at most 256 MiB, with template ids that match
  their text.
- `--report NAME` on `logfold analyze` and `logfold diff` chooses the reporter by name, so plugin reporters work from the
  command line: with `--out` it writes the file, without it the text is printed instead of the tables. The `--out` suffix `.csv`
  selects the `csv` reporter. A bad reporter or suffix fails before the logs are read.
- `--warm-start` (`warm_start=True` in `analyze` and `diff`, `ExecutionConfig.warm_start`) for the chunked strategy: the
  first chunk is mined alone and every other chunk starts from a copy of its tree. The parallel result then has far fewer stray
  templates (HDFS without masks: 45 against 341, the sequential result has 43) at the price of a serial first chunk
  (+7-50 percent of the time). It is off by default and does not change the default result. See `bench/docs/WARM_START.md`.

### Changed

- **The default diff matcher is now `jaccard`** (it was `exact`; `--matcher exact` restores the old output). It pairs a
  template that exists in one run only with its closest counterpart, such as a reworded message or one that differs in a
  host name, so `diff` reports 16-71 percent fewer false new and gone templates on saved results of real logs, at the
  same speed. A paired template is `changed`, not new, so `--fail-on-new` and `--fail-on-new-alerts` no longer fail on a
  reworded message; use `--matcher exact` for a gate that must fail on every new text. See `bench/docs/DIFF_MATCHERS.md`.
- `--strategy auto` (the default) mines sequentially when the first chunk shows that almost every record is a new template
  (more than 0.3 templates per record after 10,000 records; real logs stay below 0.03). A 100 MB log of unique messages takes
  4.2 s and 553 MB instead of 7.2 s and 1.9 GB; other logs are mined as before. An explicit `chunked` or `sequential` is never
  changed, and `metrics.strategy` shows what was used. Progress callbacks come every 1 MiB instead of every 16 MiB.
  See `bench/docs/ADAPTIVE.md`.
- `diff` and `analyze` are faster on results with many templates: the diff matchers use an index and run in the native
  extension, and the native engine hands over the templates as columns. At 18 thousand templates per run a `diff` of two
  results takes 0.19 s instead of 0.54 s, and the `jaccard` matcher no longer takes minutes (0.26 s). The output is identical.
- Plugin discovery reads the installed package metadata once instead of three times: commands start about 9 ms faster.
- `--out report.md` now writes Markdown tables (the `markdown` reporter); use `--out report.txt` or `--report text` for the
  plain text report.
- `analyze --min-count N --out result.json` writes every template to the JSON file (the option still hides rare templates
  from tables and other reports), so the file can be compared later with `diff`.
- The Python and Rust data contract is version 4: the native extension and the Python code must come from the same
  release. The algorithm version is unchanged, so results of 0.2.x are compatible.

### Fixed

- Terminal output no longer acts on control characters from log content: an escape sequence in a log line (retitle the
  window, hide text, write to the clipboard) is shown as a visible `\xNN` in the tables and in `--report` printed to a
  terminal. Files and pipes keep the raw text.

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
