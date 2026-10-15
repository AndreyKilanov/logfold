# Python API reference

Everything here is importable from `logfold`; the extension points live in `logfold.ext`. Results are frozen
dataclasses and the package is fully typed (`py.typed`).

```python
from logfold import analyze, diff
```

## `analyze`

```python
analyze(
    path, *, format=None, multiline=None, depth=None, sim_th=None,
    max_children=None, max_templates=None, on_full=None, delimiters=None,
    masks=None, high_cardinality=False, mining=None, execution=None,
    engine=None, strategy=None, threads=None, chunk_bytes=None,
    warm_start=None, examples="raw", since=None, until=None,
    values=False, value_templates=200,
    load_state=None, save_state=None, state_format="json", config=None,
    progress=None,
) -> AnalysisResult
```

Folds one run into templates.

| Argument | Meaning |
|---|---|
| `path` | one file or a sequence of files forming a single run (`str` or `PathLike`); `"-"` is standard input; gzip is detected by content |
| `format` | `None` or `"auto"` (detect it; a settings file can give another), a registered name, `"regex:<pattern>"`, `"log4j:<pattern>"`, a format specification or a `Format` object |
| `multiline` | join continuation lines to the previous record; `None` keeps the format's default |
| `depth`, `sim_th`, `max_children`, `max_templates`, `on_full`, `delimiters`, `masks` | mining parameters, see [`MiningConfig`](#mining-and-execution-configuration) |
| `high_cardinality` | fast bounded mode for data with a huge number of distinct messages |
| `mining`, `execution` | full configuration objects; the keyword arguments override their fields |
| `engine`, `strategy`, `threads`, `chunk_bytes`, `warm_start` | execution parameters, see [`ExecutionConfig`](#mining-and-execution-configuration) |
| `examples` | `"raw"` keeps example messages, `"masked"` applies the masking rules to them, `"none"` drops them |
| `since`, `until` | keep only records at or after `since` and before `until`: ISO 8601 strings (`2026-10-06T12:30`, a trailing `Z` or an offset means a zone) or `datetime` objects. A time with a zone is converted to UTC; a time without one is compared with the times of the log as written (naive times are UTC everywhere in logfold). A record without a timestamp cannot be placed and is left out. The result counts the records left out in `run.out_of_range` and `run.untimed`, the run name shows the window, and a warning mentions records without a time. A format without a time (`plain`) raises `ConfigError` |
| `values`, `value_templates` | `values=True` counts the values at the variable positions of the `value_templates` (default 200) most frequent templates into `Template.values`; it runs a second pass (the counts of the templates are then those of that pass) and takes three to four times as long; see [Values of the parameters](cli.md#values-of-the-parameters) |
| `load_state` | a state file of an earlier run to continue from: its templates start the tree, the result counts only the records of this run, and it must have been mined with the same masks and parameters. A big input is continued in parallel by default (a warning says so) and `strategy="sequential"` is the exact continuation; it needs the native engine (see [State files](cli.md#state-files)) |
| `save_state`, `state_format` | write the trained miner to this file (`.gz` is compressed), `"json"` (readable, default) or `"binary"`; the file holds templates and counts, never example lines |
| `config` | a `Settings` from [`load_config`](#load_config): it gives the format, `multiline`, `mining` and `execution` wherever the call does not name them |
| `progress` | optional callback receiving the consumed input byte count |

Raises `ConfigError`, `FormatError`, `SourceError`, `EngineError` or `StateError` (see [Errors](#errors)).

## `match`

```python
match(
    state, path, *, format=None, multiline=None, depth=None, sim_th=None,
    max_children=None, max_templates=None, on_full=None, delimiters=None,
    masks=None, mining=None, execution=None, engine=None, strategy=None,
    threads=None, chunk_bytes=None, examples="raw", since=None, until=None,
    exact=False, config=None, progress=None,
) -> AnalysisResult
```

Assigns the records of a log to the templates of a saved state (`analyze(..., save_state=...)`) without learning anything.
The state is only read. The options are those of `analyze`; the mining options and the masks must be the ones that the
state was mined with, otherwise `StateError` says so. The result is an `AnalysisResult` with the templates that were hit,
with the counts, levels and times of this log only, and `result.run.unmatched`, a `Unmatched` with `records` (records that fit
no template) and `by_length` (`(token count, records)` pairs sorted by token count; the text is not kept). `strategy` and
`threads` only decide whether the files are read in parallel: the answer is the same. With `exact=True` a record belongs to a
template only when every constant token of the template equals its token (a `<*>` accepts any token), as `TemplateMiner.match` of
Drain3 does; the default is the similarity of mining, where at least the share `sim_th` of the tokens must equal, so a record that
differs from a template in one word can still belong to it. See [`logfold match`](cli.md#logfold-match).

## `check`

```python
check(
    state, path, *, max_unmatched="default", fail_on=None, threshold_ratio=None, min_count=None,
    significance=None, diff_config=None, format=None, multiline=None, depth=None, sim_th=None,
    max_children=None, max_templates=None, on_full=None, delimiters=None, masks=None, mining=None,
    execution=None, engine=None, strategy=None, threads=None, chunk_bytes=None, examples="raw",
    since=None, until=None, config=None, progress=None,
) -> CheckResult
```

Checks a log against a saved model: the state of `analyze(..., save_state=...)`, only read. The records are matched to its
templates as in `match`, and the records that fit none are mined by themselves, which gives the templates that are new to the model
(see [`logfold check`](cli.md#logfold-check)). `max_unmatched` is the highest share of unmatched records in percent (default 1;
`None` or `"off"` does not check it), `fail_on` is `"new-alerts"` (default), `"new"` or `"none"`; both default to the `[check]`
section of `config`. The mining options and the masks must be the ones of the state, and the state must not evict templates
(`ConfigError`). The log is read in one pass; `strategy`, `threads` and `chunk_bytes` have no effect.

### `CheckResult`

| Field / method | Meaning |
|---|---|
| `passed` | `True` when there is no finding |
| `findings` | `Finding` tuple: `kind` (`unmatched`, `new` or `empty`), `message`, `value`, `threshold` |
| `unmatched` | `Unmatched`: the records that fit no template of the model |
| `unmatched_share` | their share of the records, 0 to 1 |
| `diff` | a `DiffResult`: the model is `before` (its saved counts), the log is `after`; `new_templates` are what the unmatched records form, `changed` the known templates whose share moved significantly, `disappeared` is always empty; `warnings` repeat the findings |
| `max_unmatched`, `fail_on` | the limits that were used |
| `filter(min_level=None)` | the report lists only the entries at or above `min_level`; the findings stay |
| `render`, `to_json`, `save` | `json` writes the check ([schema](schema/check-v1.schema.json)); every other reporter writes `diff` |

## `Miner`

```python
Miner(
    *, format=None, multiline=None, depth=None, sim_th=None,
    max_children=None, max_templates=None, on_full=None, delimiters=None,
    masks=None, mining=None, load_state=None, state_format="json",
    examples="raw", config=None,
)
```

A template miner that takes records as they come, instead of reading a file: a service that feeds its own messages, a
test harness, or a pipe. It keeps its templates between calls, and the result is the one that `analyze` gives in sequential
mode over the same records in the same order, whatever the sizes of the batches.

- `add_many(records) -> int` mines a batch of complete records, one string each (a record may hold several lines), in one
  native call, and returns how many were mined. This is the fast path.
- `add_log_message(message) -> int` mines one record. It crosses the native boundary once per message, so use it only for
  code that was written one message at a time.
- `add_lines(lines) -> int` and `flush() -> int` take physical lines and join continuation lines to the record before them
  as a file would be read. A record of a multi-line format stays open until the line that starts the next record arrives or
  `flush()` is called.
- `match_many(records, *, exact=False) -> list[TemplateMatch | None]` assigns a batch of complete records to the templates the miner holds and
  learns nothing: the miner, its counters and an open record stay as they were. The rule is the one of
  [`match`](#match) (`docs/ALGORITHM.md` §9): a record belongs to a template when at least the share `sim_th` of its tokens
  equals the constant tokens of the template, so it is looser than the perfect match of Drain3; with `exact=True` every constant
  token of the template must equal the token of the record (a `<*>` accepts any token), which is the match of Drain3. Every item is the
  `TemplateMatch(id, text)` of the template as the miner holds it now, or `None` for a record that fits none, is blank or
  cannot be parsed by the format; the answer for a record does not depend on the other records or on the split into calls.
  `match(record, *, exact=False)` is the same for one record and makes one native call, so use `match_many` for more.
- `new_templates() -> list[str]` returns the templates created since the previous call; a template of a loaded state is
  not reported.
- `result() -> AnalysisResult` returns the templates and counters of what was mined so far, and the miner stays usable. The
  cost is proportional to the number of templates.
- `extract_parameters(template, message)` is [`logfold.extract_parameters`](#extract_parameters) with the masks of this miner.
- `save_state(path, state_format=None)` writes a state file that `analyze(load_state=...)`, `match` and `Miner(load_state=...)`
  read, and the other way round.

The `format` is `plain` by default (the whole record is the message), and `"auto"` is refused: a stream has no file to detect
the format from (`logfold inspect FILE` finds it for a sample). The other options are those of `analyze`; the masks and the
mining parameters must be the ones a loaded state was mined with. The miner is safe to share between threads and the native
call releases the GIL, but records given by several threads are mined in the order in which the calls get the lock, so only
a single feeder gives a repeatable result, and a shared miner mines in one thread at a time. To use several cores, give every
source its own `Miner`: they run in parallel (4 miners in 4 threads: 3.3 times the lines per second of one,
`bench/docs/STREAM.md`). Memory is bounded for any stream: a record is cut at 1 MiB, a line at 16 MiB,
and the number of templates is limited by `max_templates`. Speed on a 105 MB file: `add_lines` 103 MB/s, `add_many` 86 MB/s,
`add_log_message` 34 MB/s, against 134 MB/s of `analyze` and 5 MB/s of a Drain3 loop (`bench/docs/STREAM.md`). See
[`logfold stream`](cli.md#logfold-stream).

## `diff`

```python
diff(
    before, after=None, *, format=None, multiline=None,
    threshold_ratio=None, min_count=None, min_new_count=None, recount=None,
    matcher=None, significance=None, baselines=None, min_baselines=None,
    diff_config=None, since=None, until=None, split_at=None,
    new_values=False, value_templates=200,
    <all mining and execution arguments of analyze>,
) -> DiffResult
```

Compares two runs. Both runs are mined into one shared template tree, so a template present in both is the same
template; shares are normalized by the number of records in each run. `before` and `after` accept the same values as
`path` of `analyze`; `format="auto"` detects the format from the first input of `before`.

| Argument | Default | Meaning |
|---|---|---|
| `threshold_ratio` | 2.0 | minimum factor by which a share must change to be `changed` (at least 1) |
| `min_count` | 10 | minimum records, in either run, for a template to be `changed` |
| `min_new_count` | 1 | minimum records for a template to be reported as new or disappeared |
| `split_at` | `None` | compare two parts of **one** input: give `before` only; the records before this time are the first run, the records from this time on are the second (needs a format with a time; not for saved results) |
| `since`, `until` | `None` | as in `analyze`, for both runs; with `split_at`, `since` starts the first run and `until` ends the second |
| `baselines` | `None` | more baseline runs besides `before`, each an input or a sequence of inputs; pooled into the first side, so a template is new only if no baseline has it (logs only; not with saved results or `split_at`) |
| `min_baselines` | all | with `baselines`, the number of baselines a template must occur in to be reported as disappeared or changed; a template in fewer baselines is unstable and is not reported; more than 10 baselines give a warning (every baseline is read in full) |
| `significance` | 0.01 | highest p-value of a `changed` template that is still reported, in (0, 1]; 1 keeps every template that passes the ratio and count thresholds |
| `recount` | `True` | assign every record to the finished tree for consistent counts (costs a second pass) |
| `matcher` | `"jaccard"` | registered diff matcher name: `jaccard`, `jaccard-idf`, `overlap`, `token_subset`, `exact`, `"rules:FILE"` (pairs from a file) or a plugin's (see [Choosing a matcher](guide.md#choosing-a-matcher)) |
| `diff_config` | | a full `DiffConfig`; the keyword arguments override its fields |
| `new_values`, `value_templates` | `False`, 200 | with `new_values=True`, `DiffResult.value_changes` tells which values the variable positions of the `value_templates` most frequent templates that both runs have took in the second run only (new) and in the first only (gone); see [New and gone values](#new-and-gone-values). Logs only, not with `baselines` or `recount=False` |

### New and gone values

`diff(..., new_values=True)` fills `DiffResult.value_changes`: a tuple of `TemplateValueChanges` (`id`, `text`, `level`, the most severe level of the
template in either run, and `changes`), one for each template that both runs have and whose values differ at a position. A `ValueChange` has
`position` and `name` as in [`Template.values`](#template), `new` and `gone` (the most frequent values, at most 10, as `(value, records)` pairs), `new_distinct`,
`gone_distinct`, `shared_distinct`, `before_distinct`, `after_distinct` and `capped`. The values are compared by a 64-bit fingerprint with bounded memory: a position
with more than 1,000,000 different values in a run (4,000,000 in all positions) is `capped`, has empty lists and lower-bound counts. `examples` decides how the
values are shown (`masked`: the masking rules applied and the counts summed, `none`: no lists), and `DiffResult.filter(min_level=...)` keeps the templates by their `level`. `value_changes` is `None`
without `new_values`. `ConfigError` for saved results, `baselines`, `recount=False` and `value_templates < 1`. The gates and the other lists do not depend on it.

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

## `load_config`

```python
load_config(path=None) -> Settings
```

Reads the settings file [`logfold.toml`](config.md): the file at `path`, or else the one named by `LOGFOLD_CONFIG`, or
else the first `logfold.toml` from the current folder up to the repository root. Without any file it returns the
built-in defaults. The result is passed to `analyze`, `match`, `diff` and `Miner` as `config=`; an argument of the call beats
it. `Settings` holds `format`, `multiline`, `mining` (`MiningConfig`), `execution` (`ExecutionConfig`) and `diff`
(`DiffConfig`), and `source`, the path of the file that was read. Raises `ConfigError` when the file cannot be read, is
larger than 64 KiB, is not valid TOML, or holds an unknown key, a value of the wrong type or a value out of range.

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

## `extract_parameters`

```python
extract_parameters(
    template, message, *, masks=None, mining=None, config=None,
    delimiters=None,
) -> tuple[Parameter, ...] | None
```

Gives the values that a message has at the variable positions of a template. `template` is the text of a template (or a
`Template` of a result), `message` is one record as it was written in the log. The message is masked and tokenized as the
miner does, its tokens are aligned with the template, and every variable part is given as it was written, not as the masked
token. The result is a tuple of `Parameter(position, name, value)` in the order of the positions, where `position` is the index
of the token in the template and `name` is the name of the masking rule (`num`, `ip`, `ts`, ...) or `*` for a position that
the miner generalized:

```python
>>> logfold.extract_parameters(
...     "user <NUM> logged in from <IP>", "user 42 logged in from 10.0.0.1:8080"
... )
(Parameter(position=1, name='num', value='42'),
 Parameter(position=5, name='ip', value='10.0.0.1:8080'))
```

- A `<*>` token gives one parameter with the whole token; the masked values inside it are not given again. A constant token that
  holds a masked value (`id=<NUM>`) gives one parameter named by its rule, and a rule that spans several words (`ts` matches
  `2026-10-04 12:00:01`) gives one parameter for all of them.
- The result is `None` when the message does not fit the template: another number of tokens, or a constant token that differs.
  A template without variable parts gives an empty tuple.
- The masks and the delimiters must be the ones the template was mined with (`masks=`, `mining=` or the settings in `config=`,
  as for `analyze`). The template text is split at its single spaces, as the miner joins its tokens, so the run must have used
  the space among its delimiters (the default); delimiters without the space raise `ConfigError`. The compiled masks are kept between calls, so calling the function for many
  messages is cheap. `Miner.extract_parameters(template, message)` uses the masks of the miner. See
  [`logfold params`](cli.md#logfold-params).

Raises `ConfigError` for an invalid masking rule and `EngineError` when the native extension is unavailable.

## `fetch`

```python
fetch(
    source, *, tail=None, since=None, previous=False, timeout=300.0, max_bytes=1 << 30,
) -> ContextManager[Path]
```

Runs the user's own `docker`, `kubectl` or `journalctl` (or a source that a plugin adds) and gives its output as the path
of a temporary file that exists inside the `with` block:

```python
with logfold.fetch("docker:web", tail=50_000) as path:
    result = logfold.analyze(path)
result.run.name  # 'docker:web', not the temporary path
```

`source` is `docker:NAME`, `kubectl:NAMESPACE/POD[/CONTAINER]` or `journalctl:UNIT`. **The functions that analyze a log take
paths only: a string such as `"docker:web"` given to `analyze()` is a file name, so a call never starts a program by
surprise.** Only `fetch` does, on your explicit request. It runs the program found on `PATH` (never in the current folder)
without a shell and with its input closed, reads at most `max_bytes` and waits at most `timeout` seconds; the file is private
to the user and is removed when the block ends, also on an error or an interrupt. `tail` and `since` ask the program for less
(`since` as it takes it: `15m`, `2026-10-14T10:00:00`); `previous` reads the previous instance of a `kubectl` container.

Raises `ConfigError` for a text that is not a registered source with a valid target (names are checked against narrow
patterns) or a limit that is not positive, and `SourceError` when the program is missing, fails (its first 500 characters of
error text are in the message), runs longer than `timeout`, prints more than `max_bytes` (an error, never a cut) or does not
exist on this platform (`journalctl` is for Linux). See [`logfold analyze`](cli.md#sources-reading-a-log-from-docker-kubectl-or-journalctl).

## `inspect_file`

```python
inspect_file(
    path, *, format="auto", multiline=None, limit=10, sample_lines=1000,
) -> Inspection
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
registered `formats`, `reporters`, `matchers` and `mask_sets`. It is what `logfold info` prints.

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
| `save(path, reporter=None, *, append=False, **options)` | render and write to `path`, returns the text; without `reporter` the suffix selects it (`.html`/`.htm`, `.json`, `.txt`, `.md`, `.csv`, `.xml` for `junit`, `.prom` for `prometheus`); `append=True` adds a text or Markdown report to the end of the file after a blank line (`ConfigError` for `html`, `json`, `csv`, `junit`, `prometheus`) |

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
| `values` | for a template that `analyze(values=True)` tracked, a tuple of `ValueStats` (one per variable position), otherwise `None` |

`ValueStats`: `position` (index of the token in the template), `name` (`*`, or the name of a default masking rule), `count`, `top`
(the most frequent values as `(value, count)` pairs, at most 10; empty with `examples="none"`, masked with `examples="masked"`),
`distinct` (different values counted one by one), `capped` (more than 1000 different values were met, so `distinct` is a lower
bound), `other` (values not counted one by one) and `numeric`, a `NumericSummary` (`count`, `min`, `max`, `mean`, `p50`, `p90`,
`p99`) or `None`. See [Values of the parameters](cli.md#values-of-the-parameters).

### `DiffResult`

| Field / method | Meaning |
|---|---|
| `new_templates` | present after, absent before; most frequent first |
| `disappeared` | present before, absent after; most frequent first |
| `changed` | present in both with a share ratio of at least `threshold_ratio` and a p-value of at most `significance`; largest `score` first |
| `unchanged` | number of templates present in both runs without a significant change (including the ones the test dropped) |
| `new_alerts` | the new templates whose most severe level is WARN, ERROR or FATAL |
| `value_changes` | with `new_values=True`: the new and gone values of the shared templates (`TemplateValueChanges`), otherwise `None` |
| `before`, `after` | `RunSummary` of each run |
| `config` | the `DiffConfig` used |
| `metrics`, `meta`, `warnings` | as in `AnalysisResult` |
| `filter(min_level=None)` | a new result whose `new_templates`, `disappeared` and `changed` hold only the entries at or above `min_level`; `unchanged` and the run counters stay, and `new_alerts` then follows the filtered list |
| `render`, `to_json`, `to_html`, `save` | as in `AnalysisResult` |

`DiffEntry` fields: `id`, `text` (from the second run when the template is present there), `before_count`,
`after_count`, `before_share`, `after_share`, `ratio` (`after_share / before_share`, `None` when either count is zero),
`level`, `levels` (summed over both runs), `example`, `first_seen`, `last_seen`, and for `changed` entries `score` (the
G statistic of the change of the share) and `p_value`; both are `None` for new and disappeared templates.

### `TemplateMatch`

`id` (the identifier of a template, as in `Template.id`) and `text` (the template as the miner holds it now): the template that
`Miner.match` and `Miner.match_many` assigned a record to.

### `Parameter`

`position` (index of the token in the template), `name` (the name of the masking rule, or `*` for a generalized position) and
`value` (the text as written in the message): one value that a message gave to a variable position of a template, from
[`extract_parameters`](#extract_parameters).

### `RunSummary`, `RunMetrics`, `ResultMeta`

- `RunSummary`: `name`, `files`, `lines` (physical lines read, blank ones included), `records`, `unparsed` (lines that did not become
  part of a record), `out_of_range` and `untimed` (records left out by a time window: outside it, or without a timestamp),
  `bytes`, `tz_aware` (naive timestamps are interpreted as UTC), `overflowed` (`max_templates` was
  reached), `evicted` (templates dropped to make room for new ones, `on_full="evict"`; their counts are in the catch-all
  templates; absent from the JSON report when 0), `unmatched` (set by `match`: an `Unmatched` with `records` and `by_length`; `None` for a mined run and
  absent from the JSON report) and the property `unparsed_ratio`.
- `RunMetrics`: `engine`, `strategy` (`sequential` or `chunked`: what was used, which `auto` decides), `threads`, `chunks`, and wall times `wall_total_s`, `wall_mine_s`,
  `wall_merge_s`, `wall_recount_s`, `wall_freeze_s`.
- `ResultMeta`: `schema_version`, `algo_version`, `logfold_version`, `config_hash` (results with different hashes may
  not be comparable), `format`, `degraded` (always `False`; kept for saved results).

## Mining and execution configuration

Frozen dataclasses, validated on creation (`ConfigError`). The keyword arguments of `analyze` and `diff` are sugar over
them.

```python
from logfold import MiningConfig, ExecutionConfig, DiffConfig, MaskRule

order = MaskRule("order", r"\bORD-\d+\b", "<ORDER>")
mining = MiningConfig(sim_th=0.5, masks=(order,))
result = analyze("app.log", mining=mining, execution=ExecutionConfig(threads=4))
```

| Class | Fields (defaults) |
|---|---|
| `MiningConfig` | `depth=4` (at least 3), `sim_th=0.4` (`[0, 1]`), `max_children=100`, `max_templates=100000`, `on_full="pool"` (`"evict"` drops the least recently used templates at the cap instead of pooling the new ones; one tree, sequential strategy; a state must be used with the same value), `delimiters=" \t\n\r"` (ASCII), `masks` (the default rules) |
| `ExecutionConfig` | `engine="auto"` (`auto`, `native`, `python`), `strategy="auto"` (`auto`, `sequential`, `chunked`), `threads=None` (all cores), `chunk_bytes=64 MiB`, `warm_start=False` |
| `DiffConfig` | `threshold_ratio=2.0`, `min_count=10`, `min_new_count=1`, `recount=True`, `matcher="jaccard"`, `significance=0.01`, `min_baselines=None` |
| `MaskRule` | `name`, `pattern` (must not match the empty string), `token`, `ascii=False`, `check=None` (`"luhn"` or `"iban"`: a match that fails the check is skipped) |
| `MaskSet` | `name`, `rules` (1 to 256 `MaskRule`), `version=1`, `description=""`; `fingerprint`, `to_dict()`, `MaskSet.from_dict(data)` |

`masks` replaces the default rules, which are applied in this order: `uuid` -> `<UUID>`, `ts` -> `<TS>`, `ip` -> `<IP>`,
`hex` -> `<HEX>`, `path` -> `<PATH>`, `num` -> `<NUM>`. They are available as `logfold.ext.DEFAULT_MASKS`; extend them
with `masks=(*DEFAULT_MASKS, MaskRule(...))`.

`masks` also takes **mask sets**, as objects or as the names that `logfold masks list` shows: `masks=["secrets", "pii"]` (or
`"all"`, every built-in set). The rules of the sets run first, in the order given, and the default rules run last over
the text that is left, so `masks=["payment"]` turns `4111 1111 1111 1111` into `<CARD>` and not into four `<NUM>`. A list of `MaskRule` is the full list and replaces the
defaults; rules and sets cannot be mixed in one list (`ConfigError`), an unknown name raises `UnknownMaskSetError`, a subclass of
`ConfigError` with a "did you mean" hint. A state or a saved comparison must be made with the same rules. The sets hide values in
templates and states; the examples of a result stay raw unless `examples="masked"` or `"none"`. See the
[plugins guide](plugins.md#mask-sets) for the set files and `bench/docs/MASK_SETS.md` for what the built-in sets cost.

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
| `EngineError` | `RuntimeError` | the engine failed or the native extension is unavailable |
| `StateError` | | a state file is damaged, too large, newer than this logfold, from another algorithm version, or mined with other masks or parameters |

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
| `Source`, `Command`, `SourceOptions` | protocol of a source (the program that prints a log), the command it builds, what to read |
| `register_source(source)`, `get_source(name)`, `source_names()` | register, look up and list sources |
| `MaskRule`, `MaskSet`, `DEFAULT_MASKS` | masking rules and sets of them |
| `load_mask_set(path)`, `register_mask_set(set)`, `get_mask_set(name)`, `mask_set_names()` | read a set file (`ConfigError` when it cannot be used); register, look up and list mask sets |
| `resolve_masks(selection, no_default=False)`, `mask_fingerprint(rules)` | the rules that a `masks=` selection stands for; the 16 hex digit identity of a rule list |
| `register_format`, `register_reporter`, `register_matcher` | register at runtime |
| `add_plugin_directory(path)`, `plugin_directories()`, `default_plugin_dir()` | load the plugins of a folder; the folders that are searched without being asked; the user plugin folder |
| `plugin_sources()` | every registered format, reporter, matcher, mask set and source as `(kind, name, origin)`, where `source` is `built-in` or the providing package |
| `get_format`, `get_reporter`, `get_matcher`, `format_names`, `reporter_names`, `matcher_names` | look up registered extensions |
| `reporter_for_suffix(path)` | the reporter that a report file name selects by its suffix (`UnknownSuffixError` otherwise) |
| `printable(text)` | show control characters as `\xNN`; use it on every value of a log that your reporter writes as text for people |

Plugins are discovered through the entry-point groups `logfold.formats`, `logfold.reporters`, `logfold.matchers`, `logfold.masks` and `logfold.sources`;
see the [plugins guide](plugins.md).

## Finding plugins (`logfold.plugins`)

| Name | Purpose |
|---|---|
| `list_plugins(kind=None, status=None, catalog=None)` | every format, reporter, diff matcher, mask set and source as a `PluginInfo`: `built-in`, `installed` (a package or a file in a plugin folder) or `available` (in the catalog, not installed); `status` may be one value or several; the catalog is the bundled one unless you pass another from `logfold.plugins.catalog.load()`, so nothing touches the network |
| `plugin_info(name, kind=None, catalog=None)` | the records of one name, one per kind that has it (`UnknownPluginError` with a "did you mean" hint otherwise) |
| `closest(name, kind=None, catalog=None)` | the installed and catalog names that look most like `name` |
| `unknown_name_hint(kind, name, catalog=None)` | one sentence for a name that was not found: the install command if the catalog has it, otherwise the closest names, otherwise `None`; never raises |
| `write_template(kind, name, folder=None, force=False)` | write a working plugin template into the plugin folder (or `folder`) and return its path (`ConfigError` if the file exists, `SourceError` if it cannot be written) |

`PluginInfo` has `kind`, `name`, `status`, `source`, `package`, `version`, `description`, and for available plugins
`requirement` (what pip installs), `install` (the `logfold plugins install` command), `homepage`, `min_logfold` and
`compatible` (`False` when the plugin needs a newer logfold than the one you run; `logfold.plugins.catalog.install()`
refuses it with a `ConfigError`). For a built-in format, `checked` and `not_checked` say what it was checked on (a real
program, logs of other projects, damaged logs) and what was not; they are empty for anything else.

## Compatibility

`logfold.__all__`, the CLI flags, the exit codes and the JSON schemas are stable contracts; changes to them are
recorded in the [changelog](../CHANGELOG.md). Before 1.0, breaking changes land only in a minor release.
