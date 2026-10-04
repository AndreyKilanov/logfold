# Python API reference

Everything here is importable from `logfold`; the extension points live in `logfold.ext`. Results are frozen
dataclasses and the package is fully typed (`py.typed`).

```python
from logfold import analyze, diff
```

## `analyze`

```python
analyze(path, *, format="auto", multiline=None, depth=None, sim_th=None, max_children=None, max_templates=None,
        masks=None, high_cardinality=False, mining=None, execution=None, engine=None, strategy=None, threads=None,
        chunk_bytes=None, examples="raw", progress=None) -> AnalysisResult
```

Folds one run into templates.

| Argument | Meaning |
|---|---|
| `path` | one file or a sequence of files forming a single run (`str` or `PathLike`); `"-"` is standard input; gzip is detected by content |
| `format` | `"auto"`, a registered name, `"regex:<pattern>"`, a format specification or a `Format` object |
| `multiline` | join continuation lines to the previous record; `None` keeps the format's default |
| `depth`, `sim_th`, `max_children`, `max_templates`, `masks` | mining parameters, see [`MiningConfig`](#mining-and-execution-configuration) |
| `high_cardinality` | fast bounded mode for data with a huge number of distinct messages |
| `mining`, `execution` | full configuration objects; the keyword arguments override their fields |
| `engine`, `strategy`, `threads`, `chunk_bytes` | execution parameters, see [`ExecutionConfig`](#mining-and-execution-configuration) |
| `examples` | `"raw"` keeps example messages, `"masked"` applies the masking rules to them, `"none"` drops them |
| `progress` | optional callback receiving the consumed input byte count |

Raises `ConfigError`, `FormatError`, `SourceError` or `EngineError` (see [Errors](#errors)).

## `diff`

```python
diff(before, after, *, format="auto", multiline=None, threshold_ratio=None, min_count=None, min_new_count=None,
     recount=None, matcher=None, diff_config=None, <all mining and execution arguments of analyze>) -> DiffResult
```

Compares two runs. Both runs are mined into one shared template tree, so a template present in both is the same
template; shares are normalized by the number of records in each run. `before` and `after` accept the same values as
`path` of `analyze`; `format="auto"` detects the format from the first input of `before`.

| Argument | Default | Meaning |
|---|---|---|
| `threshold_ratio` | 2.0 | minimum factor by which a share must change to be `changed` (at least 1) |
| `min_count` | 10 | minimum records, in either run, for a template to be `changed` |
| `min_new_count` | 1 | minimum records for a template to be reported as new or disappeared |
| `recount` | `True` | assign every record to the finished tree for consistent counts (costs a second pass) |
| `matcher` | `"exact"` | registered diff matcher name |
| `diff_config` | | a full `DiffConfig`; the keyword arguments override its fields |

## Results

### `AnalysisResult`

| Field / method | Meaning |
|---|---|
| `templates` | tuple of `Template`, most frequent first |
| `run` | `RunSummary` counters |
| `metrics` | `RunMetrics` execution facts |
| `meta` | `ResultMeta` provenance |
| `warnings` | tuple of human readable warnings |
| `top(n=20)` | the `n` most frequent templates |
| `render(reporter, **options)` | render with a registered reporter, returns text |
| `to_json(path=None, **options)`, `to_html(path=None, **options)` | render, write to `path` when given, return the text |

### `Template`

| Field | Meaning |
|---|---|
| `id` | stable identifier, the first 16 hex digits of `sha256(text)` |
| `text` | template text; variable parts are `<*>` or a mask token such as `<IP>` |
| `count` | records matching the template |
| `first_seen`, `last_seen` | earliest and latest timestamp, or `None` when records carry none |
| `example` | a raw message of the first matching record (`None` with `examples="none"`) |
| `level` | most severe level seen, or `None`; levels are TRACE, DEBUG, INFO, WARN, ERROR, FATAL |
| `levels` | record counts per level name |

### `DiffResult`

| Field / method | Meaning |
|---|---|
| `new_templates` | present after, absent before; most frequent first |
| `disappeared` | present before, absent after; most frequent first |
| `changed` | present in both with a share ratio of at least `threshold_ratio`; largest change first |
| `unchanged` | number of templates present in both runs without a significant change |
| `new_alerts` | the new templates whose most severe level is WARN, ERROR or FATAL |
| `before`, `after` | `RunSummary` of each run |
| `config` | the `DiffConfig` used |
| `metrics`, `meta`, `warnings` | as in `AnalysisResult` |
| `render`, `to_json`, `to_html` | as in `AnalysisResult` |

`DiffEntry` fields: `id`, `text` (from the second run when the template is present there), `before_count`,
`after_count`, `before_share`, `after_share`, `ratio` (`after_share / before_share`, `None` when either count is zero),
`level`, `levels` (summed over both runs), `example`, `first_seen`, `last_seen`.

### `RunSummary`, `RunMetrics`, `ResultMeta`

- `RunSummary`: `name`, `files`, `lines` (non-blank physical lines), `records`, `unparsed` (lines that did not become
  part of a record), `bytes`, `tz_aware` (naive timestamps are interpreted as UTC), `overflowed` (`max_templates` was
  reached), and the property `unparsed_ratio`.
- `RunMetrics`: `engine`, `strategy`, `threads`, `chunks`, and wall times `wall_total_s`, `wall_mine_s`,
  `wall_merge_s`, `wall_recount_s`, `wall_freeze_s`.
- `ResultMeta`: `schema_version`, `algo_version`, `logfold_version`, `config_hash` (results with different hashes may
  not be comparable), `format`, `degraded` (the slow reference engine was used).

## Mining and execution configuration

Frozen dataclasses, validated on creation (`ConfigError`). The keyword arguments of `analyze` and `diff` are sugar over
them.

```python
from logfold import MiningConfig, ExecutionConfig, DiffConfig, MaskRule

mining = MiningConfig(sim_th=0.5, masks=(MaskRule("order", r"\bORD-\d+\b", "<ORDER>"),))
result = analyze("app.log", mining=mining, execution=ExecutionConfig(threads=4))
```

| Class | Fields (defaults) |
|---|---|
| `MiningConfig` | `depth=4` (at least 3), `sim_th=0.4` (`[0, 1]`), `max_children=100`, `max_templates=100000`, `delimiters=" \t\n\r"` (ASCII), `masks` (the default rules) |
| `ExecutionConfig` | `engine="auto"` (`auto`, `native`, `python`), `strategy="auto"` (`auto`, `sequential`, `chunked`), `threads=None` (all cores), `chunk_bytes=64 MiB` |
| `DiffConfig` | `threshold_ratio=2.0`, `min_count=10`, `min_new_count=1`, `recount=True`, `matcher="exact"` |
| `MaskRule` | `name`, `pattern` (must not match the empty string), `token`, `ascii=False` |

`masks` replaces the default rules, which are applied in this order: `uuid` -> `<UUID>`, `ts` -> `<TS>`, `ip` -> `<IP>`,
`hex` -> `<HEX>`, `path` -> `<PATH>`, `num` -> `<NUM>`. They are available as `logfold.ext.DEFAULT_MASKS`; extend them
with `masks=(*DEFAULT_MASKS, MaskRule(...))`.

## Errors

All errors raised on purpose derive from `LogfoldError`.

| Error | Also a | Raised when |
|---|---|---|
| `ConfigError` | `ValueError` | an option or configuration value is invalid |
| `FormatError` | `ValueError` | a format is invalid, unknown or could not be detected |
| `SourceError` | | an input could not be opened or read |
| `EngineError` | `RuntimeError` | the engine failed or the requested one is unavailable |

## Reporters

`result.render(name, **options)` uses a registered reporter. Built in:

| Name | Output | Options |
|---|---|---|
| `json` | versioned JSON, schemas in [`docs/schema`](schema) | `indent` (2), `limit` (templates per list, default all) |
| `html` | self-contained page, all content escaped, strict Content-Security-Policy | `limit` (rows per table, default 2000) |
| `text` | plain text | `top` (rows per table) |
| `markdown` | Markdown tables (default plugin) | `top` (rows per table, default 20) |
| `csv` | one template per row, formula-safe (default plugin) | `top` (rows, all by default) |

`reporter_names()` in `logfold.ext` lists the registered ones, plugins included.

## Extension points (`logfold.ext`)

| Name | Purpose |
|---|---|
| `RegexFormat`, `JsonFormat`, `PlainFormat` | format specifications (data, compiled by the engine); `FormatSpec` is their union, `Format` the protocol |
| `Reporter` | protocol of a reporter: `name`, `kinds` (`analysis` and/or `diff`) and `render(result, **options) -> str` |
| `DiffMatcher` | protocol of a diff matcher |
| `MaskRule`, `DEFAULT_MASKS` | masking rules |
| `register_format`, `register_reporter`, `register_matcher` | register at runtime |
| `add_plugin_directory(path)`, `plugin_directories()`, `default_plugin_dir()` | load the plugins of a folder; the folders that are searched without being asked; the user plugin folder |
| `plugin_sources()` | every registered format, reporter and matcher as `(kind, name, source)`, where `source` is `built-in` or the providing package |
| `get_format`, `get_reporter`, `get_matcher`, `format_names`, `reporter_names` | look up registered extensions |

Plugins are discovered through the entry-point groups `logfold.formats`, `logfold.reporters` and `logfold.matchers`;
see the [plugins guide](plugins.md).

## Compatibility

`logfold.__all__`, the CLI flags, the exit codes and the JSON schemas are stable contracts; changes to them are
recorded in the [changelog](../CHANGELOG.md). Before 1.0, breaking changes land only in a minor release.
