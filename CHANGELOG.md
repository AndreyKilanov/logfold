# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/). Before 1.0, breaking changes may land in a minor release.

## [Unreleased]

### Added

- `--report NAME` on `logfold analyze` and `logfold diff` chooses the reporter by name, so plugin reporters work from
  the command line: with `--out` it writes the file, without `--out` its text is printed instead of the tables. The
  `--out` suffix `.csv` selects the `csv` reporter. An unknown or unsuitable reporter and a bad `--out` suffix now fail
  before the logs are read. A reporter that raises or returns something other than text ends with
  `error: reporter 'NAME' failed: ...` and exit code 1.
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

### Changed

- `--warm-start` (`warm_start=True` in `analyze` and `diff`, `ExecutionConfig.warm_start`) for the chunked strategy: the first chunk
  is mined alone and every other chunk starts from a copy of its tree, so the chunk trees no longer begin empty and the result
  holds far fewer stray templates (HDFS without masks: 45 against 341 with 8 MiB chunks, 43 against 102 with the default chunk;
  the sequential result has 43). It costs a serial prefix of one chunk, +7-15 percent of the time with 8 MiB chunks and +20-50
  percent with the default 64 MiB, and some memory where the tree is large. It is off by default: the default result of the
  chunked strategy and `ALGO_VERSION` are unchanged, and it does nothing for a run that is mined sequentially. The rule is in
  `docs/ALGORITHM.md` §6, the measurements in `bench/docs/WARM_START.md`. The native extension speaks contract 4 now; an
  older one is not used.
- `--strategy auto` (the default) no longer loses to the sequential strategy on logs of mostly unique messages. It starts as
  chunked above 64 MiB, and when the first chunk holds more than 0.3 templates per record after its first 10,000 records
  (real logs: at most 0.03) it cancels the chunks and mines the whole input with one tree, so the result is the sequential
  one. A 100 MB log of unique messages (8 MiB chunks) takes 4.2 s and 553 MB instead of 7.2 s and 1.9 GB; on HDFS, BGL, Spark
  and Thunderbird the strategy and the output are unchanged. An explicit `chunked` or `sequential` is never changed;
  `metrics.strategy` shows what was used. Progress callbacks now come every 1 MiB instead of every 16 MiB, so a cancel is
  noticed sooner. Measurements are in `bench/docs/ADAPTIVE.md`; the rule is in `docs/ALGORITHM.md` §8.
- **The default diff matcher is now `jaccard` instead of `exact`** (`DiffConfig.matcher`, `diff(matcher=...)`,
  `logfold diff --matcher`). It pairs a template that exists in one run only with its closest counterpart (a reworded
  message, or one that differs in a host name), so `diff` reports fewer false new/disappeared templates: on 2-3 million
  line windows of four Loghub-2.0 logs it cut the reported templates by 16-71 percent when comparing saved results and
  by 45 percent on Thunderbird in a live `diff` (on HDFS and Spark a live `diff` is unchanged). It found 184 of 206
  reworded templates in the test and joined none of 130 rewritten (different) messages with their originals. The
  time is the same on real logs (6.9-11.3 s per `diff` of 4.6-6 million lines on one thread for all three matchers) and
  +0.07 s on a worst-case `diff` of 18 thousand one-sided templates. `--matcher exact` restores the old output. A paired
  template is reported as `changed`, not as new, so `--fail-on-new` and `--fail-on-new-alerts` no longer fail on a
  reworded message; use `--matcher exact` for a gate that must fail on every new text. The evaluation and the script are
  in `bench/docs/DIFF_MATCHERS.md`; the guide has a section on choosing a matcher.
- The `token_subset` and `jaccard` diff matchers no longer compare every pair of templates: 18 thousand templates per run
  take 0.74 s and 2.2 s instead of 81 s and about 5 minutes (extrapolated); the growth exponent is 1.2 and 1.6 instead
  of 2.0, which makes `diff` of large results usable. They return exactly the pairs they returned before. Measurements
  and the script are in `bench/RESULTS.md`.
- The built-in diff matchers run in the native extension when it is available (one call per pair of template lists):
  at 18 thousand templates `token_subset` adds 0.07 s and `jaccard` 0.09 s to a `diff` instead of 0.17 s and 1.6 s; a
  whole `diff` of 100 thousand templates is projected at 4 s and 5 s. The `jaccard` words are ranks, candidates are
  filtered by the sizes of the sets and the verification stops as soon as the needed overlap is out of reach, which
  gives the same pairs. The pure-Python matchers stay the reference and
  the fallback (the pure-Python engine, a plugin or a subclass of a built-in matcher, unusual `jaccard` thresholds); the
  pairs are identical, and the rules are written in `docs/ALGORITHM.md` §10.
- `analyze` and `diff` are faster on large results: the native engine hands over the templates as columns instead of one
  dictionary per template, `Template` objects are built in one pass, and `diff` classifies the templates in the native
  extension (join by text, matcher, thresholds, order) and builds entries only for what it reports. At 18 thousand
  templates per run `diff` of two results takes 0.19 s instead of 0.54 s, the part of `analyze` outside the engine 0.07 s
  instead of 0.19 s; 72 thousand templates take 0.84 s instead of 2.6 s. The entries are identical to the pure-Python
  classification (differential tests), which stays the reference and the fallback (plugin matchers, the pure-Python
  engine); the rules are in `docs/ALGORITHM.md` §11. The Python and Rust data contract is now version 2, so the
  extension and the Python code must come from the same release.
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
