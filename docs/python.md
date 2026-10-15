# logfold in a Python program

Everything the command line does is a function. This page is the way in for someone who embeds logfold in a service, a test
or a notebook: what to call for which task. Every signature, argument and exception is in the
[API reference](api.md); this page does not repeat it.

```
pip install logfold            # the library has no dependencies; Python 3.11 or newer
```

Importing `logfold` is enough. The `cli` extra only adds the `logfold` command. The names below are in `logfold.__all__`, which
is a stable contract.

## Fold a log

```python
import logfold

result = logfold.analyze("app.log", masks=["all"], examples="none")
print(result.run.records, len(result.templates))
for template in result.top(5):
    print(template.count, template.level, template.text)

result.to_html("report.html")
result.to_json("report.json")
```

`analyze` takes a path, a list of paths for one run, or `"-"` for standard input. `result` is a frozen dataclass: `run` (what was
read: records, unparsed lines, times), `templates` (each with `count`, `share`, `level`, `first_seen`, `last_seen`, `id`) and
`meta`. The `masks` and `examples` arguments are the ones of [sharing a log safely](share-a-log.md). The
[guide](guide.md#fold-a-log-into-templates) has the same call from the command line.

## Compare two runs

```python
d = logfold.diff("before.log", "after.log")
if d.new_alerts:                       # new templates at WARN or above
    for entry in d.new_alerts:
        print(entry.after_count, entry.text)
d.to_html("diff.html")
```

`new_templates`, `disappeared` and `changed` are lists of `DiffEntry`; `diff` also takes `split_at=`, `since=`, `until=` and
`baselines=[...]`, and `matcher=` (`"jaccard"` by default). It accepts two saved results as well:
`logfold.diff(logfold.load_analysis("before.json"), logfold.load_analysis("after.json"))`. The
[incident page](incident.md) walks through reading the result.

## Keep a model and check against it

```python
logfold.analyze("good.log", save_state="model.json")      # templates and counts, never an example line

checked = logfold.check("model.json", "today.log")
if not checked.passed:
    for finding in checked.findings:
        print(finding.kind, finding.message)

matched = logfold.match("model.json", "today.log")
print(matched.run.unmatched.records)                       # records that fit no template
```

`check` fails on what the model does not know: too many unmatched records, a new template at WARN or above. The model must
have been mined with the same masks and parameters, otherwise `StateError` says so. The same file continues a run
(`analyze(..., load_state="model.json")`) and starts a stream. See [`check`](api.md#check) and [`match`](api.md#match).

## Mine a stream

```python
miner = logfold.Miner(format="app")                        # a stream cannot detect its format
miner.add_many(batch_of_records)                           # one native call per batch
for text in miner.new_templates():                          # what appeared since the last call
    print("new:", text)

miner.match(record)                                        # TemplateMatch(id, text) or None; learns nothing
result = miner.result()                                    # the same result as analyze() over the same records
miner.save_state("model.json")
```

One `Miner` mines in one thread at a time. For several sources give each its own: they run in parallel. Memory is bounded for
any stream. See [mining a stream](guide.md#mine-a-stream) and [`Miner`](api.md#miner).

## Read the values of a message

```python
logfold.extract_parameters("user <NUM> logged in from <IP>", "user 42 logged in from 10.0.0.1:8080")
# (Parameter(position=1, name='num', value='42'), Parameter(position=5, name='ip', value='10.0.0.1:8080'))
```

`analyze(..., values=True)` counts the values of the most frequent templates for a whole run: `Template.values`.

## Settings, errors, plugins

- **Settings.** A `logfold.toml` gives the format and the options you do not pass: `logfold.load_config()` finds it and
  `analyze(..., config=settings)` uses it. A keyword argument beats the file. See [settings](config.md).
- **Errors.** Everything logfold raises on purpose is a `logfold.LogfoldError`: `ConfigError`, `FormatError`, `SourceError`,
  `EngineError` and `StateError`. A missing file is a `SourceError`; catch `LogfoldError` once at the edge of your code.
- **Sources.** `with logfold.fetch("docker:web") as path:` runs `docker logs` read-only and gives the path of a temporary file
  that exists inside the block; `analyze("docker:web")` never starts a program. See [`fetch`](api.md#fetch).
- **Plugins.** A format, a report, a diff matcher, a mask set or a source is a small object you register in `logfold.ext`: see
  [plugins](plugins.md). `logfold.info()` lists what is installed; put its output in a bug report.

## Things to know

- **The work runs in native code and releases the GIL.** `analyze` on a big file uses all cores by default; pass `threads=` to
  limit it. `strategy="sequential"` gives one tree and the exact result of one run.
- **The result does not depend on the number of threads.** The strategy can change it: chunked mining of a big file can leave more
  templates than one tree (`strategy="sequential"` is the exact one).
- **`Template.id` is stable**: the first 16 hex digits of the SHA-256 of the text. Use it as a key between runs of the same
  settings.
- **Memory depends on the number of templates**, not on the size of the file (`max_templates` caps it).
- **Compatibility.** The functions and fields of `logfold.__all__`, the JSON schemas and the exit codes of the command line change
  only with a note in the [changelog](https://github.com/AndreyKilanov/logfold/blob/main/CHANGELOG.md); see
  [compatibility](api.md#compatibility).
