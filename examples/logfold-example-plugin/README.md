# logfold-example-plugin

A complete, installable logfold plugin to copy from. It adds three things, one for each extension point:

| Entry point group | Name | What it is |
|---|---|---|
| `logfold.formats` | `example` | a log format: `04/Oct/2026:10:00:01.123 WARN slow query took 412 ms` |
| `logfold.reporters` | `markdown` | a reporter that renders an analysis or a diff as Markdown tables |
| `logfold.matchers` | `first_word` | a diff matcher that pairs templates starting with the same word |

## Try it

```
pip install "logfold[cli]"
pip install ./examples/logfold-example-plugin
logfold formats                       # `example` is listed next to the built-in formats
logfold analyze examples/logfold-example-plugin/sample.log --format example
```

The reporter is used from Python:

```python
import logfold

result = logfold.analyze("examples/logfold-example-plugin/sample.log", format="example")
print(result.render("markdown", top=10))
```

The matcher is used with `diff`:

```
logfold diff before.log after.log --format example --matcher first_word
```

With the built-in `exact` matcher a reworded message (`retry failed after 3 attempts` -> `retry gave up after 3
attempts`) is reported as one new and one disappeared template; `first_word` pairs them and compares them as one.

## How it works

- `pyproject.toml` declares the objects under `[project.entry-points."logfold.formats"]`, `...reporters"` and
  `...matchers"`. Nothing is imported or registered by hand: logfold reads the entry points of the installed packages
  the first time it needs a format, a reporter or a matcher.
- A **format** is data: a `RegexFormat` (or `JsonFormat`, `PlainFormat`) that names the regular expression, the groups
  for the message, the time and the level, and the time format. The engine compiles it into its own fast parser, so a
  plugin costs nothing per line.
- A **reporter** has a `name`, the `kinds` of results it supports (`analysis`, `diff`) and a `render(result, **options)`
  method that returns text.
- A **matcher** has a `name` and `match(before_only, after_only)`, which returns index pairs of templates that describe
  the same event. Identical templates of the two runs are matched by logfold itself; the matcher only sees the rest.
- A plugin that fails to load is skipped with a warning and never breaks logfold.

See the [guide](https://github.com/AndreyKilanov/logfold/blob/main/docs/guide.md#extending-logfold) and the
[API reference](https://github.com/AndreyKilanov/logfold/blob/main/docs/api.md#extension-points-logfoldext).
