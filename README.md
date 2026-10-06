<p align="center"><b>English</b> · <a href="https://github.com/AndreyKilanov/logfold/blob/main/README.ru.md">Русский</a></p>

<p align="center">
  <img src="https://raw.githubusercontent.com/AndreyKilanov/logfold/main/docs/assets/logo.png" alt="logfold" width="240">
</p>

<h3 align="center">A library and command-line tool for large logs: folds lines into templates and compares two runs.</h3>

<p align="center">
  <a href="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="PyPI" src="https://img.shields.io/pypi/v/logfold"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/AndreyKilanov/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md"><img alt="Rust core" src="https://img.shields.io/badge/core-Rust-orange"></a>
</p>

---

logfold reads a log and replaces the variable parts of messages (numbers, IP addresses, UUIDs, paths) with masks. Lines
with the same text are then grouped into templates. For every template it counts the records, the first and last time it
appeared, the highest severity level and an example line. The `diff` command compares two runs, for example before and
after a deploy, and shows the templates that are new, gone or noticeably changed in share.

The core is written in Rust; you can use it from Python or from the command line. Everything runs locally and no data
is sent anywhere.

```
$ logfold diff before.log after.log --out diff.html --fail-on-new
before.log -> after.log: 1,265,631 -> 1,246,573 records, 2 new (2 WARN+), 1 disappeared, 3 changed, 9 unchanged, native engine, 3.41s

New templates (2)
    before      after    change  level  template
         0     44,102       new  ERROR  circuit breaker opened for upstream <IP>
         0     44,310       new  WARN   queue depth <NUM> exceeds limit on worker-<NUM>
```

## What it does

- **Templates.** `user alice failed login from 10.0.0.7` and the other lines like it are reduced to one entry,
  `user <*> failed login from <IP>`. The algorithm is compatible with Drain3. Average grouping accuracy on the 16
  Loghub-2k datasets: Drain3 0.7658, logfold in sequential mode 0.7658, in parallel mode 0.7643.
- **Comparing two runs.** Shares of templates are computed from the number of records in each run, so different log
  sizes do not matter. A template counts as changed when its share grew or fell by at least a factor of 2, it has at
  least 10 records in either run (both thresholds are configurable) and a G-test finds the change unlikely to be noise
  (`--significance`, default 0.01); the most significant changes come first. Identical inputs give an empty result.
- **One log, several baselines.** `diff app.log --split-at TIME` compares the part of one log before a time with the part
  after it (`--since` and `--until` bound any command to a time range). `--baseline` (repeatable) pools several good runs
  so that a template counts as new only if none of them has it, which removes the noise of rare messages.
- **Exit code for CI.** `--fail-on-new` exits with code 2 when there are new templates, `--fail-on-new-alerts` when any
  of them is WARN, ERROR or FATAL. A reworded message that the default matcher pairs with an old one counts as changed,
  not new; `--matcher exact` makes the gate strict. `--out FILE --append` adds a text or Markdown report to the end of a
  file instead of replacing it, so several steps of a job can write one job summary (`$GITHUB_STEP_SUMMARY`); see
  [logfold in CI](https://github.com/AndreyKilanov/logfold/blob/main/docs/ci.md).
- **Memory.** The file is read as a stream, and memory use does not depend on its size. Inputs: files, gzip, standard
  input, several files as one run.
- **Parallelism.** A large file is cut into chunks (64 MiB by default) and the chunk trees are merged in order. For a
  fixed chunk size the result does not depend on the number of threads. The strategy is chosen automatically: a large file
  is mined in parallel, and sequentially when the first chunk shows that almost every line is a new message (`--strategy
  auto`, the default). `--warm-start` starts every chunk from the tree of the first one: far fewer stray templates, at the
  price of mining the first chunk alone.
- **Value masks.** By default UUIDs, timestamps, IPs, hex values, paths and numbers are replaced; the rules can be
  changed.
- **Reports.** HTML (one file, no network requests, strict CSP), JSON with a versioned schema, text, Markdown, CSV. A
  report includes raw example lines by default; `--examples masked` or `none` removes them.
- **Extensions.** Log formats, reports and template matchers for `diff` are plugins, loaded through entry points or
  from a folder of `.py` files.

## Install

```
pip install "logfold[cli]"
```

Python 3.10 or newer. PyPI has prebuilt packages for Linux (x86_64, aarch64, musl), macOS (x86_64, arm64) and Windows
(x86_64), so pip installs without compiling and you do not need Rust. On any other platform pip builds the package from
source, which needs a Rust compiler. Without `[cli]` you get the library only.

## Quick start

Analyze a log:

```
logfold analyze app.log --top 30 --out report.html
logfold analyze app.log --only-alerts     # only WARN, ERROR and FATAL templates
logfold inspect app.log                   # how the file is read: format, first records, levels
```

The format is detected from a sample of the file (nginx, apache, syslog, journald, Kubernetes, JSON lines, logfmt and
others). If it is not sure, the command lists the candidates and asks you to pass `--format`. Indented stack-trace lines
are joined to the record that started them.

Compare two runs:

```
logfold diff before.log after.log --out diff.html --fail-on-new-alerts
logfold diff app.log --split-at 2026-10-06T12:00    # the part of one log before a time against the part after it
logfold diff good1.log after.log --baseline good2.log --baseline good3.log   # new = in none of the good runs
logfold diff before.log after.log --report markdown --out "$GITHUB_STEP_SUMMARY" --append   # in CI: add to the job summary
```

Exit codes: `0` success, `1` error, `2` something requested by a `--fail-on-*` flag was found.

Compare saved results without reading the logs again:

```
logfold analyze before.log --out before.json
logfold analyze after.log  --out after.json
logfold diff before.json after.json
```

A JSON file written with `--out` holds every template, so it is suitable for this kind of comparison.

See which formats, reports and matchers you have, and which plugins you can still install:

```
logfold plugins list                      # built-in, installed and available from the catalog
logfold plugins info NAME                 # what a plugin does and how to install or use it
```

## From Python

```python
from logfold import analyze, diff, load_analysis

result = analyze("app.log")  # the format is detected
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")
result.filter(min_level="WARN").save("alerts.md")  # the reporter comes from the suffix

comparison = diff("before.log", "after.log")
comparison.new_templates
comparison.new_alerts  # new WARN/ERROR/FATAL templates
comparison.to_html("diff.html")

# compare saved results
diff(load_analysis("before.json"), load_analysis("after.json"))
```

`analyze()` and `diff()` return immutable dataclass objects.

## Formats and parameters

| | |
|---|---|
| Formats | `nginx`, `apache`, `nginx-error`, `syslog`, `journald`, `k8s` (CRI/containerd), `jsonl`, `app` (`<time> LEVEL message`), `logfmt`, `serilog-clef`, `haproxy`, `postgresql`, `postgresql-csv`, `docker-json`, `github-actions`, `log4j` (or your own `log4j:<pattern>`), `plain`, your own `regex:<pattern>`. List: `logfold formats`. |
| Multi-line records | `--multiline`; with `--format auto` it turns on by itself when indented lines are found. |
| Folding | `--depth` (4), `--sim-th` (0.4), `--max-children` (100), `--max-templates` (100000). The defaults are the same as in Drain3. |
| Execution | `--strategy auto` (default; parallel chunks, sequential for logs of unique messages), `sequential`, `chunked`; `--threads`, `--chunk-mb`; `--warm-start` (opt-in, chunked only). |
| Logs with almost unique lines | `--high-cardinality`: at most 5000 templates, the rest go into catch-all templates, runs sequentially. On a 10 MB file with 84 thousand distinct lines 2.0 s becomes 0.14 s. |
| Reports | HTML, JSON, text, Markdown, CSV; the `--out` suffix picks the format, `--report NAME` picks the report explicitly, including one from a plugin. |
| Matchers for `diff` | `jaccard` (default), `jaccard-idf`, `overlap`, `rules:FILE` (your own pairs), `token_subset`, `exact`: they link a reworded message to its earlier version so it is not counted as both new and gone. |
| Plugins | `logfold plugins list` (built-in, installed, available), `info NAME`, `check`, `install NAME`, `new`; an unknown format, report or matcher name gets a hint with the closest name or the install command. In Python: `logfold.plugins.list_plugins()`. |
| Scripting | `--json` prints JSON to stdout, exit codes are stable, the JSON format is described by a schema in `docs/schema`. |

## Speed

Measured on one machine (8 cores, Windows 11); the protocol was fixed before the runs, details and data are in
[`bench/RESULTS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md).

| | logfold, 16 threads | [Drain3](https://github.com/logpai/Drain3) (Python) |
|---|---:|---:|
| nginx access log, 100 MB | 0.38 s | 5.26 s |
| application log, 100 MB | 0.41 s | 9.03 s |
| nginx access log with value masking | 0.45 s | 26.82 s |
| HDFS, 1.57 GB, a real log | 0.94 s | not measured |
| `diff` of two 100 MB logs | 0.7 s | no `diff` |

On the real logs of 0.7 to 1.6 GB peak memory is 42 to 51 MB with one thread and 107 to 129 MB with 16 threads.

## Limitations

> **Warning.** Keep these in mind before running logfold on large logs and comparing results.
>
> - Speed was measured on Windows 11 only; on Linux and macOS correctness is tested, but speed is not.
> - The parallel mode builds a tree per chunk and merges them, so on logs without masks it can return more templates
>   than the sequential mode (HDFS without masks: 341 against 43; `--warm-start` brings it to 45 at the cost of a
>   serial first chunk). On logs with a very large number of distinct
>   messages the default `auto` strategy notices that after the first chunk and mines sequentially; `--high-cardinality`
>   makes it faster still.
> - Saved results are compared without a recount against a shared template tree, so the same event can end up both in
>   new and in gone; the matcher (`jaccard` by default) exists for this.

## Measurements and bug reports

logfold was measured on one machine (Windows 11, 8 cores). If you can run it on other hardware (Linux, macOS, ARM, a
slower disk, more cores) or on your own logs, we would be glad to get the numbers. We also want to hear about wrong
results, crashes, templates that are grouped badly, and runs that are slow or use too much memory.

- **Measurements.** Run the benchmark as described in [`bench/README.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/README.md) (the protocol is
  in [`bench/PROTOCOL.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/PROTOCOL.md)) or time your own command, and open a
  [performance issue](https://github.com/AndreyKilanov/logfold/issues/new?template=performance.yml). Include the wall time, throughput and peak memory, the
  command, the size and format of the input, the CPU and number of cores, RAM, disk type, OS, the logfold version and
  the number of threads.
- **Bugs.** Open a [bug report](https://github.com/AndreyKilanov/logfold/issues/new?template=bug_report.yml) with what you expected and what happened, a
  command or Python snippet that reproduces it, the output of `logfold --version` and `logfold info`, and a few lines of
  the input with secrets removed.

All issue forms are listed on the [new issue page](https://github.com/AndreyKilanov/logfold/issues/new/choose); how issues are written is described in
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md#issues).

## How it compares to other tools

| | logfold | [Drain3](https://github.com/logpai/Drain3) | [logdrain](https://github.com/vnvo/logdrain) | [logdelta](https://github.com/antonsoo/logdelta) |
|---|---|---|---|---|
| Language | Rust core, Python API and CLI | Python | Rust | Rust |
| Template quality | same as Drain3 on Loghub-2k | reference | Drain | Drain-based |
| Comparing two runs | yes (`diff`, shares normalized, recount) | no | no (online "template created" signal) | yes (`diff`, several baselines, blocks) |
| Python API | yes | yes | no | no |
| Multi-threaded mining of one big file | yes, deterministic | no | not documented for the CLI | not documented |
| Reports | JSON, HTML, text, Markdown, CSV | - | text, JSON, CSV | terminal, JSON, Markdown |

Template quality: `python eval/quality.py` (grouping accuracy on the 16 Loghub-2k datasets).

## Documentation

- [Guide](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md): formats, parameters, plugins, engines.
- [Using logfold in CI](https://github.com/AndreyKilanov/logfold/blob/main/docs/ci.md): GitHub Actions and GitLab CI, job
  summary, gates, where the baseline comes from.
- [Command-line reference](https://github.com/AndreyKilanov/logfold/blob/main/docs/cli.md): commands, options, exit
  codes.
- [Plugins](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md): using and writing formats, reports and
  matchers; an example package is in
  [`examples/logfold-example-plugin`](https://github.com/AndreyKilanov/logfold/tree/main/examples/logfold-example-plugin).
- [Python API reference](https://github.com/AndreyKilanov/logfold/blob/main/docs/api.md).
- [Algorithm](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md),
  [JSON schemas](https://github.com/AndreyKilanov/logfold/tree/main/docs/schema) and the
  [changelog](https://github.com/AndreyKilanov/logfold/blob/main/CHANGELOG.md).

## Design

A pure core (masking, tokenizer, Drain-compatible tree, merge) with no I/O, adapters for files and formats, an
execution layer, a thin PyO3 shim, and a Python package on top. The algorithm is described in
[`docs/ALGORITHM.md`](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md). A pure-Python reference
engine implements the same specification, and the Rust engine is tested against it for exactly equal results.

## Development

Rules for branches, commits and the definition of done are in
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md). Report vulnerabilities
privately, see [SECURITY.md](https://github.com/AndreyKilanov/logfold/blob/main/SECURITY.md).

## License

MIT, see [LICENSE](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE). Copyright (c) 2026 Andrey Kilanov.
