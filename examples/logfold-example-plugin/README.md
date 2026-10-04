# logfold-example-plugin

A complete, installable set of logfold plugins to copy from: three log formats, two reporters and two diff matchers.
The full instruction on using and writing plugins is in the
[plugins guide](https://github.com/AndreyKilanov/logfold/blob/main/docs/plugins.md).

| Kind | Name | What it is |
|---|---|---|
| format | `logfmt` | `key=value` lines: `ts=2026-10-04T10:00:01Z level=warn msg="slow query" took=412ms` (regex) |
| format | `serilog-clef` | Serilog compact JSON with `@t`, `@m` / `@mt`, `@l` (JSON) |
| format | `ci-blocks` | a log made of blocks that start with `=== `; indented lines belong to the block (plain, multiline) |
| reporter | `markdown` | Markdown tables for an analysis or a diff |
| reporter | `csv` | one template per row, for spreadsheets and scripts |
| matcher | `first_word` | pairs templates that start with the same word |
| matcher | `jaccard` | pairs templates whose words overlap by at least 60% |

## Try it

```
pip install "logfold[cli]"
pip install ./examples/logfold-example-plugin

logfold formats                                    # logfmt, serilog-clef and ci-blocks are listed
cd examples/logfold-example-plugin/samples
logfold analyze app.logfmt --format logfmt
logfold analyze serilog.jsonl --format serilog-clef
logfold analyze ci.log --format ci-blocks
logfold diff before.logfmt after.logfmt --format logfmt                       # exact: 1 new, 1 disappeared
logfold diff before.logfmt after.logfmt --format logfmt --matcher jaccard     # paired: 0 new, 0 disappeared
```

Reporters are used from Python:

```python
import logfold

result = logfold.analyze("app.logfmt", format="logfmt")
print(result.render("markdown", top=10))
print(result.render("csv"))
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
