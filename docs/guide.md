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
d.changed  # share of the log changed by at least threshold_ratio (default 2.0)
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
| `--strategy` | auto | `sequential` (one tree), `chunked` (parallel), `auto` (chunked above 64 MiB) |
| `--threads`, `--chunk-mb` | all cores, 64 | parallel execution |
| `--examples` | raw | `masked` or `none` before sharing a report |

The parallel strategy cuts the file into fixed-size chunks, builds one tree per chunk and merges the trees in order. For
a fixed chunk size the result does not depend on the number of threads.

### High-cardinality data

Free-form text, random ids or hashes in every line can produce one template per line. Mining that is slow and
memory-hungry for any Drain-based tool. `--high-cardinality` (`high_cardinality=True` in Python) caps the templates at
5000 (unless you pass `--max-templates`), pools every further record into catch-all templates (`<*> <*> ...`, one per
token count; counts stay exact) and runs sequentially, because merging huge trees costs more than parallelism saves.
On a 10 MB file with about 84 000 distinct lines this turns 2.0 s into 0.14 s. A warning tells you when the cap was hit,
also without the mode.

## Extending logfold

Plugins are ordinary Python packages that declare entry points.

```toml
[project.entry-points."logfold.formats"]
haproxy = "my_plugin:HAPROXY"

[project.entry-points."logfold.reporters"]
markdown = "my_plugin:MarkdownReporter"

[project.entry-points."logfold.matchers"]
first_word = "my_plugin:FirstWordMatcher"
```

```python
from logfold.ext import RegexFormat

HAPROXY = RegexFormat(
    name="haproxy",
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
