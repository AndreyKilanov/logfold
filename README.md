<p align="center"><b>English</b> · <a href="https://github.com/AndreyKilanov/logfold/blob/main/README.ru.md">Русский</a></p>

<p align="center">
  <img src="https://raw.githubusercontent.com/AndreyKilanov/logfold/main/docs/assets/logo.png" alt="logfold" width="240">
</p>

<h3 align="center">Fold a million log lines into a dozen templates, and see exactly what changed between two runs.</h3>

<p align="center">
  <a href="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml/badge.svg"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="PyPI" src="https://img.shields.io/pypi/v/logfold"></a>
  <a href="https://pypi.org/project/logfold/"><img alt="Python versions" src="https://img.shields.io/pypi/pyversions/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/LICENSE"><img alt="License: MIT" src="https://img.shields.io/github/license/AndreyKilanov/logfold"></a>
  <a href="https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md"><img alt="Rust core" src="https://img.shields.io/badge/core-Rust-orange"></a>
</p>

---

Your service misbehaves after a deploy. The log is 2 GB of lines that all look alike, and `grep` only finds what you
already suspect. **logfold** turns the noise into a short list of message templates with counts, severities and
examples, and **compares two runs** to show what is new, what disappeared and what suddenly became frequent. It works
offline, on your machine, in seconds. No platform to run, no data to upload.

```
$ logfold diff before.log after.log --out diff.html --fail-on-new
before.log -> after.log: 1,265,631 -> 1,246,573 records, 2 new (2 WARN+), 1 disappeared, 3 changed, 9 unchanged, native engine, 3.41s

New templates (2)
    before      after    change  level  template
         0     44,102       new  ERROR  circuit breaker opened for upstream <IP>
         0     44,310       new  WARN   queue depth <NUM> exceeds limit on worker-<NUM>
```

## ✨ Why you will like it

| | |
|---|---|
| 🧩 **A million lines, a dozen templates** | `user alice failed login from 10.0.0.7` and a million siblings become one line, `user <*> failed login from <IP>`, with a count, first and last timestamp, severity and an example. The grouping is identical to [Drain3](https://github.com/logpai/Drain3) on Loghub-2k. |
| 🔍 **See what a deploy changed** | `diff` compares two runs: new, disappeared and changed templates, normalized by run size, so a bigger log does not look like a regression. Identical inputs give an empty diff. |
| 🚦 **A gate for CI** | `--fail-on-new-alerts` exits with code 2 when a new WARN, ERROR or FATAL template shows up. One line turns a log into a test. |
| ⚡ **Fast on a laptop** | A Rust core streams the file with memory that does not grow with its size and mines it on all cores: 100 MB in 0.4 s, a 1.6 GB HDFS log in about one second, the same result for any number of threads. |
| 📄 **Reports people open** | A self-contained HTML page (no network, strict CSP), JSON with a versioned schema, Markdown, CSV and plain text. |
| 🔒 **Private by default** | Everything runs locally. Values such as UUIDs, IPs and numbers are masked, and `--examples masked` or `none` keeps raw lines out of a report you share. |
| 🐍 **A Python library first** | `analyze()` and `diff()` return plain, immutable dataclasses; the CLI is a thin layer over the same API. |
| 🔌 **Yours to extend** | Log formats, reporters and diff matchers are plugins; `logfold plugins` lists and installs more, and a folder of your own `.py` files is enough. |

## 🚀 Install

```
pip install "logfold[cli]"
```

Wheels for Linux, macOS and Windows (Python 3.10+) mean nothing is compiled on your machine. Without `[cli]` you get
the library only.

## 🧭 Three things to try

**1. Understand a log.**

```
logfold analyze app.log --top 30 --out report.html
```

The format is detected for you (nginx, apache, syslog, journald, Kubernetes, JSON lines, logfmt and more), gzip files
are read as they are, `-` reads standard input, and indented stack-trace lines are joined to the record that started them.

**2. Compare before and after a deploy.**

```
logfold diff before.log after.log --out diff.html --fail-on-new-alerts
```

Open `diff.html` for the tables, or let CI read the exit code (`0` fine, `2` something new and bad, `1` error).

**3. Compare later, without the logs** (*new in 0.3.0*).

```
logfold analyze before.log --out before.json
logfold analyze after.log  --out after.json
logfold diff before.json after.json --matcher token_subset
```

Keep the small JSON reports instead of gigabytes of logs and compare any two of them whenever you like.

## 🐍 From Python

```python
from logfold import analyze, diff, load_analysis

result = analyze("app.log")  # format auto-detected
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")

comparison = diff("before.log", "after.log")
comparison.new_templates
comparison.new_alerts  # new WARN/ERROR/FATAL templates
comparison.to_html("diff.html")

# new in 0.3.0: compare saved results
diff(load_analysis("before.json"), load_analysis("after.json"))
```

## 🧰 What it can do

| | |
|---|---|
| **Formats** | `nginx`, `apache`, `nginx-error`, `syslog`, `journald`, Kubernetes (`k8s`), JSON lines, `app` (`<time> LEVEL message`), `logfmt`, Serilog CLEF, `plain`, or your own `regex:<pattern>`. `--format auto` samples the file and says so when it is unsure. |
| **Inputs** | Files, gzip, standard input, several files as one run. Multi-line records (stack traces) with `--multiline`. |
| **Masking** | UUIDs, timestamps, IPs, hex, paths and numbers become `<UUID>`, `<IP>`, `<NUM>`, ...; the rules are yours to change. |
| **Hard data** | `--high-cardinality` for logs where almost every line is unique: bounded memory and much faster (2.0 s down to 0.14 s on a 10 MB file). |
| **Reports** | HTML, JSON, text, Markdown and CSV; `--report NAME` (*0.3.0*) picks any reporter, including your own. |
| **Diff** | New, disappeared and changed templates; thresholds you control; matchers (`exact`, `token_subset`, `jaccard`) that pair a reworded message with its old version. |
| **Plugins** | `logfold plugins list`, `check`, `install`, `new`; entry points or a plain folder of `.py` files. |
| **Scripting** | Stable exit codes, `--json` on stdout, a documented JSON schema. |

## ⚡ How fast

Measured on one machine (8 cores, Windows 11), the protocol was fixed before the runs. More in
[`bench/RESULTS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md).

| | logfold, 16 threads | [Drain3](https://github.com/logpai/Drain3) (Python) |
|---|---:|---:|
| nginx access log, 100 MB | **0.38 s** | 5.26 s |
| application log, 100 MB | **0.41 s** | 9.03 s |
| nginx access log with value masking | **0.45 s** | 26.82 s |
| HDFS, 1.57 GB, real log | **0.94 s** | not measured |
| `diff` of two 100 MB logs | **0.7 s** | no `diff` |

On the 0.7 to 1.6 GB real logs memory peaks at about 45 MB with one thread and 110 MB with 16 threads.

## 🆚 How it relates to other tools

| | logfold | [Drain3](https://github.com/logpai/Drain3) | [logdrain](https://github.com/vnvo/logdrain) | [logdelta](https://github.com/antonsoo/logdelta) |
|---|---|---|---|---|
| Language | Rust core, Python API + CLI | Python | Rust | Rust |
| Template quality | identical to Drain3 on Loghub-2k | reference | Drain | Drain-based |
| Compare two runs | yes (`diff`, shares normalized, recount) | no | no (online "template created" signal) | yes (`diff`, several baselines, blocks) |
| Python API | yes | yes | no | no |
| Multi-threaded mining of one big file | yes, deterministic | no | not documented for the CLI | not documented |
| Reports | JSON, HTML, text, Markdown, CSV | - | text, JSON, CSV | terminal, JSON, Markdown |

Template quality: `python eval/quality.py` (grouping accuracy on the 16 Loghub-2k datasets).

## 📚 Documentation

- [Guide](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md): formats, parameters, plugins, engines.
- [Command-line reference](https://github.com/AndreyKilanov/logfold/blob/main/docs/cli.md): every command, option and
  exit code.
- [Plugins](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md): use and write formats, reporters and
  diff matchers; a complete example package is in
  [`examples/logfold-example-plugin`](https://github.com/AndreyKilanov/logfold/tree/main/examples/logfold-example-plugin).
- [Python API reference](https://github.com/AndreyKilanov/logfold/blob/main/docs/api.md): `analyze`, `diff`, results,
  configuration, errors, reporters and extension points.
- [Algorithm](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md), [JSON
  schemas](https://github.com/AndreyKilanov/logfold/tree/main/docs/schema) and the
  [changelog](https://github.com/AndreyKilanov/logfold/blob/main/CHANGELOG.md).

## 🏗️ Design

Layered: a pure domain core (masking, tokenizer, Drain-compatible tree, merge) with no I/O, adapters for files and
formats, an execution layer, a thin PyO3 shim, and a Python package on top. The algorithm is specified in
[`docs/ALGORITHM.md`](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md); a pure-Python reference
engine implements the same specification, and the Rust engine is tested against it for exact equality.

## 🤝 Contributing

Issues and pull requests are welcome, see
[CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md) (branches, commits, issues,
definition of done). Report vulnerabilities privately, see
[SECURITY.md](https://github.com/AndreyKilanov/logfold/blob/main/SECURITY.md).

## 📜 License

MIT, see [LICENSE](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE). Copyright (c) 2026 Andrey Kilanov.
