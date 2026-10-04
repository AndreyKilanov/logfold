# Changelog

All notable changes are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/) and the
project uses [Semantic Versioning](https://semver.org/). Before 1.0, breaking changes may land in a minor release.

## [Unreleased]

### Added

- Default plugins inside `pip install logfold`: formats `logfmt` and `serilog-clef`, reporters `markdown` and `csv`
  (CSV cells that a spreadsheet would read as a formula are neutralized), diff matcher `jaccard`.
- `logfold plugins list|check|install`: list every format, reporter and matcher with its source, show the plugins of a
  catalog that are not installed yet, and install one with pip after confirmation. The catalog is bundled and works
  offline; `--online` fetches the latest one over HTTPS, `--catalog` takes a file or an HTTPS URL, and
  `LOGFOLD_OFFLINE=1` forbids network access.
- `logfold.ext.plugin_sources()`.
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
