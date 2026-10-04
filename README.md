# logfold

[![CI](https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml/badge.svg)](https://github.com/AndreyKilanov/logfold/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/logfold)](https://pypi.org/project/logfold/)
[![Python versions](https://img.shields.io/pypi/pyversions/logfold)](https://pypi.org/project/logfold/)
[![License: MIT](https://img.shields.io/github/license/AndreyKilanov/logfold)](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE)
[![Rust core](https://img.shields.io/badge/core-Rust-orange)](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md)

**Fold large logs into templates, and see what changed between two runs.** A Python library and command-line tool
with a Rust core, for offline analysis of big log files: no platform to run, no data to upload.

```
$ logfold diff before.log after.log --out diff.html --fail-on-new
before.log -> after.log: 1,265,631 -> 1,246,573 records, 2 new (2 WARN+), 1 disappeared, 3 changed, 9 unchanged, native engine, 3.41s

New templates (2)
    before      after    change  level  template
         0     44,102       new  ERROR  circuit breaker opened for upstream <IP>
         0     44,310       new  WARN   queue depth <NUM> exceeds limit on worker-<NUM>
```

- **Templates.** `user alice failed login from 10.0.0.7` and a million siblings become one line
  `user <*> failed login from <IP>` with a count, first and last timestamp, severity and an example.
- **Diff.** Compare two runs (before and after a deploy, passing and failing CI job). New, disappeared and changed
  templates, normalized by run size. Identical inputs produce an empty diff.
- **Fast.** Rust core, streaming I/O with memory independent of the file size, deterministic multi-threaded mining.
  See [benchmarks](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md).
- **A Python library first.** `analyze()` and `diff()` return plain, immutable dataclasses; reports are JSON (versioned
  schema), self-contained HTML or text.
- **Extensible.** Formats, reporters and diff matchers are plugins discovered through entry points; a default set
  (`logfmt`, `serilog-clef`, `markdown`, `csv`, `jaccard`) ships with logfold and `logfold plugins` lists, checks and
  installs more.

## Install

```
pip install "logfold[cli]"
```

Wheels are published for Linux, macOS and Windows (Python 3.10+), so nothing is compiled on your machine.

## Use

```python
from logfold import analyze, diff

result = analyze("app.log")  # format auto-detected
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")

comparison = diff("before.log", "after.log")
comparison.new_templates
comparison.new_alerts  # new WARN/ERROR/FATAL templates
comparison.to_html("diff.html")
```

```
logfold analyze app.log --top 30 --out report.html          # fold one run into templates
logfold diff before.log after.log --fail-on-new-alerts      # exit code 2 in CI when something new is wrong
logfold formats                                             # list the log formats
logfold info                                                # versions and engine availability, for bug reports
logfold plugins check                                       # plugins you do not have yet; `install NAME` adds one
logfold --version
```

## Documentation

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

## How it relates to other tools

| | logfold | [Drain3](https://github.com/logpai/Drain3) | [logdrain](https://github.com/vnvo/logdrain) | [logdelta](https://github.com/antonsoo/logdelta) |
|---|---|---|---|---|
| Language | Rust core, Python API + CLI | Python | Rust | Rust |
| Template quality | identical to Drain3 on Loghub-2k | reference | Drain | Drain-based |
| Compare two runs | yes (`diff`, shares normalized, recount) | no | no (online "template created" signal) | yes (`diff`, several baselines, blocks) |
| Python API | yes | yes | no | no |
| Multi-threaded mining of one big file | yes, deterministic | no | not documented for the CLI (library `add` is thread-safe) | not documented |
| Reports | JSON, HTML, text | - | text, JSON, CSV | terminal, JSON, Markdown |

Timings are in [`bench/RESULTS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/RESULTS.md), measured with the [protocol](https://github.com/AndreyKilanov/logfold/blob/main/bench/PROTOCOL.md) that was fixed
before the runs. Template quality: `python eval/quality.py` (grouping accuracy on the 16 Loghub-2k datasets).

## Design

Layered: a pure domain core (masking, tokenizer, Drain-compatible tree, merge) with no I/O, adapters for files and
formats, an execution layer, a thin PyO3 shim, and a Python package on top. The algorithm is specified in
[`docs/ALGORITHM.md`](https://github.com/AndreyKilanov/logfold/blob/main/docs/ALGORITHM.md); a pure-Python reference engine implements the same specification, and the Rust
engine is tested against it for exact equality.

## Development

See [CONTRIBUTING.md](https://github.com/AndreyKilanov/logfold/blob/main/CONTRIBUTING.md) (branches, commits, issues, definition of done).

## License

MIT, see [LICENSE](https://github.com/AndreyKilanov/logfold/blob/main/LICENSE). Copyright (c) 2026 Andrey Kilanov.
