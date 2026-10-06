# logfold guide

This guide walks through the typical tasks. For the complete lists of options and signatures see the
[command-line reference](cli.md) and the [Python API reference](api.md).

## Install

```
pip install "logfold[cli]"        # library, native engine and the `logfold` command
pipx install "logfold[cli]"       # just the command
```

The core library has no dependencies. The `cli` extra adds `typer` and `rich`. Python 3.10 or newer.

## Fold a log into templates

```python
from logfold import analyze

result = analyze("app.log")  # format is detected
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")  # self-contained, works offline
result.to_json("report.json")  # schema: docs/schema/analysis-v1.schema.json
```

```
logfold analyze app.log --top 20 --out report.html
```

Several files can form one run (`analyze(["app.log.1.gz", "app.log"])` in Python, `logfold analyze app.log.1.gz app.log`
on the command line), `-` reads standard input and gzip files are detected by content.

A template looks like `user <*> failed login from <IP>`: `<*>` is a variable part, `<IP>`, `<NUM>`, `<UUID>`, `<TS>`,
`<HEX>` and `<PATH>` are values replaced by the default masking rules before mining.

## Compare two runs

```python
from logfold import diff

d = diff("before.log", "after.log")
d.new_templates  # present after, absent before (most frequent first)
d.disappeared
d.changed  # share changed by at least threshold_ratio (default 2.0) and significantly (p <= 0.01); largest score first
d.new_alerts  # new templates whose most severe level is WARN or higher
d.to_html("diff.html")
```

```
logfold diff before.log after.log --out diff.html --fail-on-new
```

Exit codes: `0` success, `1` error, `2` new templates found with `--fail-on-new` (or new WARN/ERROR/FATAL templates
with `--fail-on-new-alerts`).

Shares are normalized by the number of records in each run, so runs of different size are comparable. Both runs are
mined into one shared template tree, and then **every record of both runs is assigned to the finished tree** (the
`recount` pass), so identical lines always land in the same template. `--no-recount` skips the second pass and is
faster but can show spurious differences.

### Compare two parts of one log

An incident often sits inside one file. Cut the log at a time and compare what came before with what came after:

```python
diff("app.log", split_at="2026-10-06T12:00")
diff("app.log", split_at="2026-10-06T12:00", since="2026-10-06T11:00", until="2026-10-06T13:00")  # an hour each side
```

```
logfold diff app.log --split-at 2026-10-06T12:00 --since 2026-10-06T11:00 --until 2026-10-06T13:00
```

`since` and `until` also work in `analyze` (`logfold analyze app.log --since ... --until ...`) to look at a part of a log.
Times are ISO 8601. A time with a zone is converted to UTC; a time without one is compared with the times in the log as
written. A record without a timestamp cannot be placed, so it is left out and counted (`run.untimed`); records outside
the window are counted in `run.out_of_range` and do not enter the shares.

### Compare with several baselines

A template missing from one good run may still be normal. Give `diff` more good runs and it reports as `new` only what
none of them has:

```python
diff("good1.log", "after.log", baselines=["good2.log", "good3.log"])
diff("good1.log", "after.log", baselines=["good2.log", "good3.log"], min_baselines=2)
```

```
logfold diff good1.log after.log --baseline good2.log --baseline good3.log --min-baselines 2
```

The baselines are mined with one template tree and pooled: counts and records add up, and shares are normalized by the
pooled records. By default a template must occur in every baseline to be reported as `disappeared` or `changed`;
`min_baselines` lowers that bar. A template that occurs in some baselines, but in fewer than the minimum, is unstable:
it is never reported as new, disappeared or changed. Baselines are logs only, not saved results or `--split-at`. Each baseline is read in full, so time and memory grow with
their number. Three to five recent good runs are enough to tell stable templates from noise; more than ten give a
warning.

### Compare saved results

Analyze each log once, keep the JSON, and compare the reports later without the logs:

```python
from logfold import analyze, diff, load_analysis

analyze("before.log").to_json("before.json")
analyze("after.log").to_json("after.json")
d = diff(load_analysis("before.json"), load_analysis("after.json"))
```

```
logfold diff before.json after.json
```

The reports were mined separately, with no shared tree and no `recount` pass, so the same event can appear as new in
one and disappeared in the other; a matcher pairs such templates, and a warning says so. Analyze both logs with the same
masks and parameters (the `config_hash` of the reports must match, or a warning is added). Examples are kept as saved:
choose `examples="masked"` or `"none"` when analyzing if they may hold sensitive values.

### Choosing a matcher

A template that exists in one run only can be paired with its closest counterpart, so a reworded message, or one that differs in
a host name, is compared as one template instead of being reported as one new and one disappeared template. The matcher decides
what counts as the same template: `--matcher NAME` on the command line, `matcher="NAME"` in Python.

| | `jaccard` (default) | `token_subset` | `exact` |
|---|---|---|---|
| what it pairs | templates that share enough words (Jaccard similarity of the word sets, at least 0.6) | templates of equal length where one generalizes the other (`<*>` against a word) | nothing: a template is the same only if its text is the same |
| speed | the same as the others on real logs; +0.07 s on a worst-case `diff` of 18 thousand one-sided templates | +0.03 s on the same | the fastest, by those fractions of a second |
| accuracy | the best: 16-71 percent fewer false alarms on saved results; finds 89 percent of the reworded messages in the tests | 2-62 percent fewer false alarms on saved results; finds no reworded message | no pairing, every reword is a new and a disappeared template |
| risk | may join two similar templates that are different messages (1 pair of 206 in the tests) | only safe merges (one template generalizes the other) | none |

Three more matchers ship as default plugins, all computed by the Rust core:

| | `jaccard-idf` | `overlap` | `rules:FILE` |
|---|---|---|---|
| what it pairs | Jaccard similarity where a word weighs `1 / (templates that contain it)`, at least 0.5: shared rare words count, shared common words hardly | `shared words / words of the shorter template`, at least 0.8, for templates of three words or more: an extended or shortened message | the pairs you list, one `TEMPLATE <=> TEMPLATE` per line, `<*>` matches any token |
| use it when | `jaccard` joins siblings that differ in a rare word | a message got longer and `jaccard` falls below its threshold | you know the rewording and no similarity rule gets it |
| risk | one shared rare word (a host, an id) can outweigh many different common ones | joins a short template with a long one that merely contains its words (4 of about 280 pairs in the reworded-all test) | none beyond your rules |

None of them beats `jaccard` on the measurements in [`bench/docs/DIFF_MATCHERS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/DIFF_MATCHERS.md#the-040-matchers-accuracy):
`jaccard-idf` pairs about half as many unrelated templates and never merged two different messages there, `overlap` merged some,
so `jaccard` stays the default.

In a `diff` of two logs (the shared tree and the recount) `token_subset` and `exact` give the same result, because the recount
already merges generalizations; `jaccard` differs only where templates keep host names or other literals. For saved results the
three differ most. The exit-code gates (`--fail-on-new`, `--fail-on-new-alerts`) count new templates only, and a paired template is
`changed`, so use `--matcher exact` for a gate that must fail on every new text. Measurements on four large real logs, and how they were made, are in
[`bench/docs/DIFF_MATCHERS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/DIFF_MATCHERS.md).

## Reports

`--out FILE` writes a report; the suffix selects the format: `.html`, `.json`, `.txt` (plain text), `.md` (Markdown tables)
or `.csv`. `--report NAME` picks the reporter by name instead, including one from a plugin: with `--out` it writes the
file, without it the text is printed instead of the tables. HTML reports are one self-contained file with a strict
Content-Security-Policy. JSON files follow the schemas in `docs/schema`.

## Formats

`logfold formats` lists them. `--format auto` (the default) samples the file and picks one; it fails with the best
guesses instead of guessing wrong silently.

| Name | Input |
|---|---|
| `plain` | the whole line is the message |
| `jsonl` | one JSON object per line; keys `message`/`msg`/`log`, `timestamp`/`time`/`ts`/`@timestamp`, `level`/`severity`/`lvl` |
| `journald` | `journalctl -o json` |
| `nginx`, `apache` | combined access log; the message is `"METHOD path HTTP/x" status` |
| `nginx-error` | nginx error log |
| `syslog` | classic syslog lines |
| `k8s` | CRI/containerd container logs (`kubectl logs` raw files) |
| `app` | `<ISO timestamp> [thread] LEVEL message`, typical of Python, Java and Go services |
| `logfmt` | `key=value` pairs (default plugin); `msg`, `time`/`ts` and `level` keys are used |
| `serilog-clef` | Serilog compact JSON (default plugin); `@m`/`@mt`, `@t`, `@l` |
| `haproxy` | HAProxy HTTP and TCP logs, with or without the syslog prefix (default plugin) |
| `postgresql`, `postgresql-csv` | PostgreSQL server log, `stderr` and `csvlog` (default plugins) |
| `docker-json` | Docker `json-file` driver lines: `log`, `time` (default plugin) |
| `github-actions` | GitHub Actions job logs; `##[error]`, `##[warning]`, `##[debug]` are levels (default plugin) |
| `log4j` | log4j and logback output in the pattern `%d{ISO8601} %-5p [%t] %c - %m%n` (default plugin) |
| `log4j:<pattern>` | log4j or logback output in your own conversion pattern, for example `log4j:%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n` |
| `regex:<pattern>` | your own pattern; named groups `message`/`msg`, `timestamp`/`time`/`ts`, `level`/`lvl` are used |

Multi-line records (stack traces): `--multiline` joins lines that do not start a record to the previous one. With
`--format auto` indented continuation lines enable it automatically.

## Parameters

| Option | Default | Meaning |
|---|---|---|
| `--depth` | 4 | tree depth (Drain3 convention, minimum 3) |
| `--sim-th` | 0.4 | similarity threshold: a line joins a template when at least this share of tokens matches exactly |
| `--max-children` | 100 | children per tree node |
| `--max-templates` | 100000 | cap on templates; further records are pooled into catch-all templates |
| `--no-masks` | off | do not mask values |
| `--high-cardinality` | off | mode for data with a huge number of distinct messages (see below) |
| `--strategy` | auto | `sequential` (one tree), `chunked` (parallel), `auto` (chunked above 64 MiB, sequential when almost every record is a new template) |
| `--threads`, `--chunk-mb` | all cores, 64 | parallel execution |
| `--examples` | raw | `masked` or `none` before sharing a report |

The parallel strategy cuts the file into fixed-size chunks, builds one tree per chunk and merges the trees in order. For
a fixed chunk size the result does not depend on the number of threads. With `auto`, the first chunk is watched: when
after its first 10 000 records it holds more than 0.3 templates per record (logs of unique messages), merging the chunk trees
would cost more than it saves, and the whole input is mined with one tree instead. `metrics.strategy` shows what was used.

A chunk tree begins empty, so the first records of every chunk are generalized before the common templates exist, and the stray
templates that result cannot be merged back: the parallel result holds more rare templates than the sequential one (HDFS without
masks: 341 against 43; the large templates are the same). `--warm-start` (`warm_start=True`) trains the first chunk alone and
starts every other chunk from a copy of its tree, which removes most of the strays. The price is a serial prefix of one chunk (a
smaller `--chunk-mb` makes it cheaper) and a copy of the tree per chunk; it does not apply to the sequential strategy, and
it is off by default. Numbers: [`bench/docs/WARM_START.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/WARM_START.md).

### High-cardinality data

Free-form text, random ids or hashes in every line can produce one template per line. Mining that is slow and
memory-hungry for any Drain-based tool. `--high-cardinality` (`high_cardinality=True` in Python) caps the templates at
5000 (unless you pass `--max-templates`), pools every further record into catch-all templates (`<*> <*> ...`, one per
token count; counts stay exact) and runs sequentially, because merging huge trees costs more than parallelism saves.
On a 10 MB file with about 84 000 distinct lines this turns 2.0 s into 0.14 s. A warning tells you when the cap was hit,
also without the mode. With `--strategy auto` such a log is noticed after the first chunk and mined sequentially even
without the mode, but the mode is faster and keeps the result short.

## Extending logfold

Plugins are ordinary Python packages that declare entry points.

The [plugins guide](plugins.md) explains how to use and write each kind (formats, reporters, diff matchers); a complete
installable example is in [`examples/logfold-example-plugin`](../examples/logfold-example-plugin).

```toml
[project.entry-points."logfold.formats"]
myapp = "my_plugin:MYAPP"

[project.entry-points."logfold.reporters"]
markdown = "my_plugin:MarkdownReporter"

[project.entry-points."logfold.matchers"]
first_word = "my_plugin:FirstWordMatcher"
```

```python
from logfold.ext import RegexFormat

MYAPP = RegexFormat(
    name="myapp",
    pattern=r"^(?P<ts>\d{2}/\w{3}/\d{4}:[\d:.]+) (?P<lvl>\w+) (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    ts_format="%d/%b/%Y:%H:%M:%S.%f",
)
```

A format plugin returns **data** (a `RegexFormat`, `JsonFormat` or `PlainFormat`), not code: the engine compiles it into
a fast parser, so plugins cost nothing per line. `Reporter` and `DiffMatcher` are protocols in `logfold.ext`.

## Engines

`engine="auto"` uses the Rust engine and falls back to a slow pure-Python reference engine with a warning when the
extension is missing. The reference engine is also the oracle that the Rust engine is tested against; for the
sequential strategy both give identical results (`docs/ALGORITHM.md`). Set `LOGFOLD_ENGINE=python` to force it.

## Security

Log lines are untrusted: HTML reports escape everything and carry a strict Content-Security-Policy. Example messages
are raw lines; use `--examples masked` or `none` before sharing a report. See `SECURITY.md`.
