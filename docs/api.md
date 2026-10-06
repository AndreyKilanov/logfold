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
        chunk_bytes=None, warm_start=None, examples="raw", progress=None) -> AnalysisResult
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
| `engine`, `strategy`, `threads`, `chunk_bytes`, `warm_start` | execution parameters, see [`ExecutionConfig`](#mining-and-execution-configuration) |
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
| `matcher` | `"jaccard"` | registered diff matcher name: `jaccard`, `token_subset`, `exact` or a plugin's (see [Choosing a matcher](guide.md#choosing-a-matcher)) |
| `diff_config` | | a full `DiffConfig`; the keyword arguments override its fields |

### Comparing saved results

`before` and `after` can also be two `AnalysisResult` objects, straight from `analyze` or loaded with
`load_analysis`. Nothing is re-read: templates are joined by id, templates present in one result only are paired by the
`matcher`, and the counts are the saved ones. The results were mined separately and are **not** re-counted against a
shared tree, so the same event can show up as both new and disappeared; the default `jaccard` matcher pairs most such cases.
The result carries a warning about this, and about different `config_hash` or `format` values. Results of different
`algo_version` raise `ConfigError`. Options that control reading or mining (`format`, `multiline`, `recount`, `depth`,
`sim_th`, `max_children`, `max_templates`, `masks`, `high_cardinality`, `mining`, `execution`, `engine`, `strategy`,
`threads`, `chunk_bytes`, `warm_start`, `progress`) raise `ConfigError` in this mode. `examples="none"` drops the saved examples;
`examples="masked"` raises `ConfigError`, because the masking rules are not saved: the examples stay as they were
written, so analyze with `examples="masked"` or `"none"` before saving if they may contain sensitive values. The
result reports `config.recount == False`.

```python
before = analyze("before.log")
before.to_json("before.json")
...
result = diff(load_analysis("before.json"), load_analysis("after.json"))
```

## `load_analysis`

```python
load_analysis(path) -> AnalysisResult
```

Loads a JSON report written by `AnalysisResult.to_json()` or `logfold analyze --out result.json`. The report must hold
every template (not be written with `limit`). The file must be UTF-8 (a BOM is accepted) and at most 256 MiB, every
template id must equal `sha256(text)[:16]` and be unique; otherwise, or when the file is not an analysis report of
schema version 1, `SourceError` is raised.

`is_saved_analysis(path) -> bool` tells whether a file is such a report rather than a log: it reads the first 4096 bytes and
looks for the header `{"schema_version": N, "kind": "analysis"`. It is `False` for a log and for a file that cannot be read.
A UTF-16 file (a PowerShell 5 `>` redirect) counts as a report, so that `load_analysis` can explain what is wrong with it.

## `inspect_file`

```python
inspect_file(path, *, format="auto", multiline=None, limit=10, sample_lines=1000) -> Inspection
```

Shows how a file is read without mining it: the format that was detected or applied, the first `limit` records as parsed
and, from the first `sample_lines` non-blank lines, the level counts, the time range and the number of lines that did not
parse. Only a bounded part of the file is read (a line longer than 1 MiB is cut, and reading stops after 8 MiB), so it is
quick on any size. It is the function behind `logfold inspect`. Standard input is not supported (`SourceError`).

`Inspection` fields: `path`, `size`, `compressed` (gzip), `spec` (the format specification that was applied), `confidence`
(`None` unless the format was auto-detected), `multiline_auto`, `lines`, `records`, `unparsed`, `truncated` (the file has
more lines than the sample), `shown` (a tuple of `InspectedRecord`: `message`, `time`, `level`, `lines`), `levels` (records
per level in the sample), `no_level`, `first_time`, `last_time`.

## `info`

```python
info() -> Info
```

The facts that a bug report needs, as a frozen dataclass: `version`, `python`, `native_available`, `core_version`,
`contract_version`, `algo_version` (the last three are `None` without the native extension), and the sorted names of the
registered `formats`, `reporters` and `matchers`. It is what `logfold info` prints.

## Results

### `AnalysisResult`

| Field / method | Meaning |
|---|---|
| `templates` | tuple of `Template`, most frequent first |
| `run` | `RunSummary` counters |
| `metrics` | `RunMetrics` execution facts |
| `meta` | `ResultMeta` provenance |
| `warnings` | tuple of human readable warnings; they also say when `warm_start` or `chunk_bytes` was ignored because the run was sequential |
| `top(n=20)` | the `n` most frequent templates |
| `levels` | records per level name over all templates (only levels that occurred, least severe first) |
| `filter(min_level=None, min_count=None)` | a new result with only the templates whose most severe level is at least `min_level` (`TRACE` to `FATAL`, any case; `warning` is accepted) and that have at least `min_count` records; the run counters, metrics and meta stay as they were |
| `render(reporter, **options)` | render with a registered reporter, returns text |
| `to_json(path=None, **options)`, `to_html(path=None, **options)` | render, write to `path` when given, return the text |
| `save(path, reporter=None, **options)` | render and write to `path`, returns the text; without `reporter` the suffix selects it (`.html`/`.htm`, `.json`, `.txt`, `.md`, `.csv`) |

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
| `filter(min_level=None)` | a new result whose `new_templates`, `disappeared` and `changed` hold only the entries at or above `min_level`; `unchanged` and the run counters stay, and `new_alerts` then follows the filtered list |
| `render`, `to_json`, `to_html`, `save` | as in `AnalysisResult` |

`DiffEntry` fields: `id`, `text` (from the second run when the template is present there), `before_count`,
`after_count`, `before_share`, `after_share`, `ratio` (`after_share / before_share`, `None` when either count is zero),
`level`, `levels` (summed over both runs), `example`, `first_seen`, `last_seen`.

### `RunSummary`, `RunMetrics`, `ResultMeta`

- `RunSummary`: `name`, `files`, `lines` (non-blank physical lines), `records`, `unparsed` (lines that did not become
  part of a record), `bytes`, `tz_aware` (naive timestamps are interpreted as UTC), `overflowed` (`max_templates` was
  reached), and the property `unparsed_ratio`.
- `RunMetrics`: `engine`, `strategy` (`sequential` or `chunked`: what was used, which `auto` decides), `threads`, `chunks`, and wall times `wall_total_s`, `wall_mine_s`,
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
| `ExecutionConfig` | `engine="auto"` (`auto`, `native`, `python`), `strategy="auto"` (`auto`, `sequential`, `chunked`), `threads=None` (all cores), `chunk_bytes=64 MiB`, `warm_start=False` |
| `DiffConfig` | `threshold_ratio=2.0`, `min_count=10`, `min_new_count=1`, `recount=True`, `matcher="jaccard"` |
| `MaskRule` | `name`, `pattern` (must not match the empty string), `token`, `ascii=False` |

`masks` replaces the default rules, which are applied in this order: `uuid` -> `<UUID>`, `ts` -> `<TS>`, `ip` -> `<IP>`,
`hex` -> `<HEX>`, `path` -> `<PATH>`, `num` -> `<NUM>`. They are available as `logfold.ext.DEFAULT_MASKS`; extend them
with `masks=(*DEFAULT_MASKS, MaskRule(...))`.

## Errors

All errors raised on purpose derive from `LogfoldError`. Its `hint` attribute is a short suggestion for the next step, or
`None`; `str(error)` stays one sentence about what went wrong. The errors for a name that is not registered
(`UnknownFormatError`, `UnknownReporterError`, `UnknownMatcherError`, and `UnknownPluginError` for `plugin_info()`,
importable from `logfold.errors`) carry `name` and `known` and suggest the closest name in `hint`; `FormatDetectionError` carries `path` and `guesses`; `UnknownSuffixError`
(a report file name that selects no reporter) carries `path` and `suffixes`; `NoLevelsError` (a level filter on a result whose
format gives no levels) carries `format`. They are subclasses of `FormatError` and `ConfigError`, so existing handlers keep
working.

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

Log content is untrusted, so no built-in reporter returns a raw control character. `text`, `markdown`, `csv` and `html` pass
every value that comes from a log through `logfold.ext.printable`: escape sequences, bell and the other C0, DEL and C1
control characters are shown as `\xNN` instead of reaching your terminal, and tabs and line feeds are kept. `json` escapes
them as `\uNNNN`, which parses back to the same text. The values on the result objects (`Template.text`,
`Template.example`, ...) are data and stay raw: pass them through `printable` before printing them yourself.

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
| `get_format`, `get_reporter`, `get_matcher`, `format_names`, `reporter_names`, `matcher_names` | look up registered extensions |
| `reporter_for_suffix(path)` | the reporter that a report file name selects by its suffix (`UnknownSuffixError` otherwise) |
| `printable(text)` | show control characters as `\xNN`; use it on every value of a log that your reporter writes as text for people |

Plugins are discovered through the entry-point groups `logfold.formats`, `logfold.reporters` and `logfold.matchers`;
see the [plugins guide](plugins.md).

## Finding plugins (`logfold.plugins`)

| Name | Purpose |
|---|---|
| `list_plugins(kind=None, status=None, catalog=None)` | every format, reporter and diff matcher as a `PluginInfo`: `built-in`, `installed` (a package or a file in a plugin folder) or `available` (in the catalog, not installed); `status` may be one value or several; the catalog is the bundled one unless you pass another from `logfold.plugins.catalog.load()`, so nothing touches the network |
| `plugin_info(name, kind=None, catalog=None)` | the records of one name, one per kind that has it (`UnknownPluginError` with a "did you mean" hint otherwise) |
| `closest(name, kind=None, catalog=None)` | the installed and catalog names that look most like `name` |
| `unknown_name_hint(kind, name, catalog=None)` | one sentence for a name that was not found: the install command if the catalog has it, otherwise the closest names, otherwise `None`; never raises |
| `write_template(kind, name, folder=None, force=False)` | write a working plugin template into the plugin folder (or `folder`) and return its path (`ConfigError` if the file exists, `SourceError` if it cannot be written) |

`PluginInfo` has `kind`, `name`, `status`, `source`, `package`, `version`, `description`, and for available plugins
`requirement` (what pip installs), `install` (the `logfold plugins install` command), `homepage`, `min_logfold` and
`compatible` (`False` when the plugin needs a newer logfold than the one you run; `logfold.plugins.catalog.install()`
refuses it with a `ConfigError`).

## Compatibility

`logfold.__all__`, the CLI flags, the exit codes and the JSON schemas are stable contracts; changes to them are
recorded in the [changelog](../CHANGELOG.md). Before 1.0, breaking changes land only in a minor release.
