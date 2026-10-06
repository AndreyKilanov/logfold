# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/). Before 1.0, breaking changes may land in a minor release.

## [Unreleased]

### Added

- The library gets what only the command line had. `AnalysisResult.filter(min_level=, min_count=)` and
  `DiffResult.filter(min_level=)` keep the templates at or above a level (the `--level` and `--only-alerts` filter, with the
  same rules: a format without levels raises `NoLevelsError`), `AnalysisResult.levels` sums the records per level,
  `result.save(path, reporter=None)` writes a report and picks the reporter from the suffix,
  `logfold.is_saved_analysis(path)` tells a saved report from a log, `logfold.inspect_file()` (the function behind
  `inspect`) with `Inspection` and `InspectedRecord`, and `logfold.info()` with `Info` (what `logfold info` prints).
  `logfold.ext` gains `printable()`, `reporter_for_suffix()` and `matcher_names()`, and `logfold.errors` gains
  `UnknownSuffixError` and `NoLevelsError`. Level names and helpers live in `logfold.levels`.
- `logfold inspect FILE` shows how a file is read without mining it: the detected format and its confidence, the first records
  as parsed (time, level, message), and from a sample of the start of the file the level counts, the time range and the
  number of unparsed lines, with hints for a format that does not fit. `--records`, `--sample-lines`, `--json`.
- `--level LEVEL` and `--only-alerts` on `logfold analyze` and `logfold diff` keep the templates whose most severe level is at
  least LEVEL (`--only-alerts` is `--level WARN`). In `analyze` the tables and reports are filtered and a `.json` file
  from `--out` stays complete; in `diff` the lists, the reports and the `--fail-on-new*` gates all use the filtered result. A
  format without levels is an error with a hint.
- Terminal output: a `levels:` line in the `analyze` summary, "N more templates (X% of records)" with the option that shows
  them, `wrote report.html  (open it in a browser)` after an HTML report, and the transfer speed in the progress indicator.
- `logfold analyze --help` and `logfold diff --help` group the options into panels (Input, Output, Diff, Mining, Execution,
  General) and end with examples; `--min-count` and `--matcher` say what they do in the command. The flags and their defaults
  are unchanged.
- `result.warnings` says when `warm_start` (`--warm-start`) was given but the run was sequential, and the same for
  `chunk_bytes` (`--chunk-mb`) when something other than a small input with `strategy="auto"` made it sequential (the python
  engine, `high_cardinality`, `strategy="sequential"`), instead of ignoring the option silently; the command line prints it with the other warnings. The warning for
  `warm_start` on the python engine moved from the `logging` output to `result.warnings`.
- Errors carry a next step: `LogfoldError.hint`, and in the CLI a `hint:` line under `error:`. A misspelled format, reporter
  or diff matcher suggests the closest name (`did you mean 'nginx'?`) and the command that lists them, an undetected format
  names `-f plain` and `-f regex:<pattern>`, and `--out` without a known suffix lists the suffixes. New subclasses
  `UnknownFormatError`, `UnknownReporterError`, `UnknownMatcherError` and `FormatDetectionError` (in `logfold.errors`) hold the
  details; they derive from `FormatError` and `ConfigError`, so existing `except` clauses keep working.

### Changed

- The `text` and `markdown` reporters pass every value taken from a log through `logfold.ext.printable`: escape sequences,
  bell and other control characters are shown as \xNN instead of being returned raw, so printing a report on a terminal
  cannot be driven by the log. Only text that contained control characters changes; `csv` keeps the raw values and `json` and
  `html` escape them in their own way. The command line reports an unwritable `--out` file as an error instead of a traceback,
  and `logfold info` also lists the diff matchers.
- Format detection (and `inspect`) reads a bounded sample: a line longer than 1 MiB is cut there and reading stops after
  8 MiB, so a file that is one huge line, or a gzip bomb, no longer makes `--format auto` allocate memory in proportion to
  the file (a 300 MiB single line took 600 MiB before).
- Error messages are shorter and read the same on every system: a path is shown as is (no doubled backslashes on Windows) and
  is not wrapped at the terminal width, a missing file says `no such file` instead of repeating the path with the system's
  localized text, and text such as `[red]` in a path is printed literally instead of being read as markup.
  `--engine` and `--strategy` errors list the valid values. The advice that ended the undetected-format message ("pass a
  format explicitly...") is now `error.hint`, so `str(error)` no longer contains it.

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
