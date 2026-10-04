# logfold-example-plugin

A complete, installable set of logfold plugins to copy from: three log formats, two reporters and two diff matchers.
The full instruction on using and writing plugins is in the
[plugins guide](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md).

logfold already ships `logfmt`, `serilog-clef`, `markdown`, `csv` and `jaccard` as
[default plugins](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md#default-plugins). The plugins here
are teaching copies, so their names start with `example-` and never replace the built-in ones.

| Kind | Name | What it is |
|---|---|---|
| format | `example-logfmt` | `key=value` lines: `ts=2026-10-04T10:00:01Z level=warn msg="slow query" took=412ms` (regex) |
| format | `example-serilog-clef` | Serilog compact JSON with `@t`, `@m` / `@mt`, `@l` (JSON) |
| format | `example-ci-blocks` | a log made of blocks that start with `=== `; indented lines belong to the block (plain, multiline) |
| reporter | `example-markdown` | Markdown tables for an analysis or a diff |
| reporter | `example-csv` | one template per row, for spreadsheets and scripts |
| matcher | `example-first-word` | pairs templates that start with the same word |
| matcher | `example-jaccard` | pairs templates whose words overlap by at least 60% |

## Try it

```
pip install "logfold[cli]"
pip install ./examples/logfold-example-plugin

logfold plugins list                               # the example-* plugins are listed with their package as the source
cd examples/logfold-example-plugin/samples
logfold analyze app.logfmt --format example-logfmt
logfold analyze serilog.jsonl --format example-serilog-clef
logfold analyze ci.log --format example-ci-blocks
logfold diff before.logfmt after.logfmt --format example-logfmt                               # 1 new, 1 disappeared
logfold diff before.logfmt after.logfmt --format example-logfmt --matcher example-jaccard    # paired: 0 and 0
```

Reporters are used from Python:

```python
import logfold

result = logfold.analyze("app.logfmt", format="example-logfmt")
print(result.render("example-markdown", top=10))
print(result.render("example-csv"))
```

## Layout

```
pyproject.toml                  entry points: the only place where logfold is told about the plugins
logfold_example_plugin/
  formats.py                    LOGFMT (RegexFormat), SERILOG_CLEF (JsonFormat), CI_BLOCKS (PlainFormat)
  reporters.py                  MarkdownReporter, CsvReporter
  matchers.py                   FirstWordMatcher, JaccardMatcher
samples/                        small logs for every format and a before/after pair for the matchers
```

The tests in the logfold repository (`tests/test_example_plugin.py`) keep the example working with the current logfold.
