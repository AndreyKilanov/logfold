# Plugins

logfold can be extended with three kinds of plugins. A plugin is an ordinary Python package; logfold finds it through
entry points as soon as it is installed, with no configuration.

| Kind | Adds | Entry point group | Used as |
|---|---|---|---|
| Format | a way to read one more log format | `logfold.formats` | `--format NAME`, `format="NAME"` |
| Reporter | one more output format of a result | `logfold.reporters` | `result.render("NAME")` |
| Diff matcher | a rule that pairs reworded templates in `diff` | `logfold.matchers` | `--matcher NAME`, `matcher="NAME"` |

logfold ships a set of [default plugins](#default-plugins), `logfold plugins` [lists, checks and installs](#managing-plugins)
more, and [Writing a plugin](#writing-a-plugin) explains how to make your own. A complete, installable package with
three formats, two reporters and two matchers is in [`examples/logfold-example-plugin`](../examples/logfold-example-plugin).

## Default plugins

They are part of `pip install logfold`; nothing else has to be installed.

| Kind | Name | What it does |
|---|---|---|
| format | `logfmt` | `key=value` lines such as `ts=2026-10-04T10:00:01Z level=warn msg="slow query" took=412ms` |
| format | `serilog-clef` | Serilog compact JSON (`@t`, `@m` / `@mt`, `@l`) |
| format | `haproxy` | HAProxy HTTP and TCP logs (`option httplog`, `option tcplog`), with or without the syslog prefix; the message runs from the frontend to the end of the line, so the termination state (`----`, `sH--`) is part of the template |
| format | `postgresql` | the `stderr` log; any `log_line_prefix` that starts with a timestamp; `DETAIL`, `HINT` and `STATEMENT` lines are records of their own, indented continuation lines of a statement join the record |
| format | `postgresql-csv` | `csvlog`: severity is the 12th column, the message the 14th |
| format | `docker-json` | Docker `json-file` driver: `{"log": "...", "stream": "stdout", "time": "..."}` |
| format | `github-actions` | job logs with 7-digit timestamps and a leading byte-order mark; `##[error]`, `##[warning]`, `##[notice]` and `##[debug]` are the level, other `##[...]` commands stay in the message |
| format | `log4j` | the pattern `%d{ISO8601} %-5p [%t] %c - %m%n`; stack traces join their record; any other pattern: `log4j:<pattern>` |
| reporter | `markdown` | Markdown tables for an analysis or a diff |
| reporter | `csv` | one template per row, for spreadsheets and scripts |
| matcher | `jaccard` | the default matcher of `diff`: pairs templates whose words overlap by at least 60%, so a reworded message is one template |

```
logfold analyze app.logfmt --format logfmt
logfold diff before.logfmt after.logfmt --format logfmt --matcher jaccard
```

None of the format plugins is picked by `--format auto`: name the one you need (`--format haproxy`).

### log4j and logback patterns

`--format "log4j:<pattern>"` (library: `format="log4j:<pattern>"`) turns the conversion pattern of your appender into a
format, so the layout is written once, where it is already known:

```
logfold analyze app.log --format "log4j:%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n"
```

```python
from logfold.ext import log4j_format

spec = log4j_format("%d{yyyy-MM-dd HH:mm:ss,SSS} %-5p [%t] %c - %m%n", name="shop")
result = logfold.analyze("app.log", format=spec)
```

Understood: `%d` (`ISO8601`, `ABSOLUTE`, `DATE`, or a Java date pattern built from `y M d H m s S` and `X`/`Z` for an
offset), `%p`/`%level`, `%m`/`%msg`, `%c`/`%logger`, `%t`/`%thread`, the other plain fields (`%C %F %L %M %r %X{key} %x
%u`), `%ex` and its relatives (the stack trace is printed on the following lines and joins the record), `%%`, a trailing
`%n`, and width modifiers such as `%-5p`. A converter that is not understood (`%highlight`, `%replace`, `%d{EEE}`)
fails before any log is read, with a hint to write the format as `regex:<pattern>`. Records are multi-line by default,
so stack traces join the line that started them; `--no-multiline` turns that off.

```python
result = logfold.analyze("app.logfmt", format="logfmt")
print(result.render("markdown", top=10))
open("templates.csv", "w", encoding="utf-8").write(result.render("csv"))
```

Reporters are used from Python with `result.render(...)`, which raises `ConfigError` for an unknown reporter, or for a
result kind the reporter does not support, and from the command line with `--report NAME` on `analyze` and `diff`:
with `--out` the named reporter writes the file, without it its text is printed instead of the tables. `--out` alone
chooses by file suffix (`.html`, `.json`, `.txt`, `.md`, `.csv`). A typo in the name fails before any log is read.

With the `exact` matcher (`--matcher exact`) a reworded message (`retry failed after 3 attempts` -> `retry gave up after 3
attempts`) is one *new* and one *disappeared* template. A matcher pairs them, and `diff` compares the pair as one
template. The reporters neutralize log content for their target: CSV cells that a spreadsheet would read as a formula
(`=`, `+`, `-`, `@`) get a leading apostrophe, and Markdown table cells cannot be broken by `|` or backticks.

A plugin package that registers the same name replaces a default one; pick another name unless you mean to.

## Managing plugins

```
logfold plugins list                       # every format, reporter and matcher: built in, installed, available
logfold plugins info NAME                  # what one plugin does, where it is from, how to install or use it
logfold plugins check                      # plugins of the catalog that are not installed yet
logfold plugins install NAME               # install one of them (asks for confirmation)
```

`list` gives each plugin a status: `built-in` (the defaults), `installed` (a package, or a file in your plugin folder) and
`available` (in the catalog, not installed yet). `--installed`, `--available` and `--kind format|reporter|matcher` narrow
the list. It is the quickest way to see that an installed plugin was found, and to find the name of one you can install
(`logfold formats` and `logfold info` show the names too). `info NAME` shows the package and version, the description, the
install command for an available plugin and an example of use for an installed one. A misspelled name gets a
"did you mean" from the installed and catalog names. Both take `--online` and `--catalog` like `check`.

The same names help where you type them: `unknown format 'traefik'` ends with a `hint:` that says the plugin is available
and how to install it, `logfold formats` lists the format plugins of the catalog, and `analyze --help` shows the
available ones next to `--format`, `--report` and `--matcher`. A plugin that needs a newer logfold is marked
`needs logfold X.Y.Z` in `list`, `info` and `formats`, and `install` refuses it (upgrade logfold first).

The **catalog** is a short list of known plugin packages. By default it is the one bundled with your version of logfold:
`check` works offline, and new plugins show up after `pip install -U logfold`. To see the newest list without upgrading:

```
logfold plugins check --online             # fetches the latest catalog over HTTPS
logfold plugins check --catalog my.json    # a file or an https URL of your own
```

`LOGFOLD_OFFLINE=1` forbids every network access of these commands. Nothing else in logfold reads the catalog, and
`analyze` and `diff` never use the network.

`install` accepts only names that are in the catalog. It shows the package, the version constraint, the description and
where the catalog came from, asks for confirmation (`--yes` skips the question) and runs
`python -m pip install <package><constraint>` in the environment that runs logfold. A plugin is Python code that runs
with your privileges, so read what is offered. A catalog is validated strictly (safe names, version constraints,
printable text, size limits), so an entry cannot smuggle options into pip. If pip is not available in the environment
(for example a `uv` environment), `uv pip install` is used; without both, the command says so and prints the package to
install with your installer.

The catalog format:

```json
{
  "schema_version": 1,
  "plugins": [
    {
      "name": "traefik",
      "kinds": ["format"],
      "package": "logfold-traefik",
      "specifier": ">=0.2,<1",
      "description": "HAProxy HTTP logs",
      "homepage": "https://example.org/logfold-traefik",
      "min_logfold": "0.4.0"
    }
  ]
}
```

`kinds` is a non-empty list of `format`, `reporter` and `matcher`; `specifier`, `homepage` and `min_logfold` (the oldest logfold the plugin works with, as `X.Y.Z`) are optional. The bundled
catalog is `python/logfold/plugins/catalog.json` in the repository, and the file on the `main` branch is what
`--online` reads. To list your plugin there, open a pull request that adds an entry.

## Using other plugin packages

Install the package into the environment that runs logfold, then check that logfold sees it:

```
pip install ./examples/logfold-example-plugin
logfold plugins list          # the new names appear with the package as the source
logfold formats               # formats are also listed here
logfold info                  # versions, engine, and the names of all formats and reporters
```

The example package registers its plugins as `example-logfmt`, `example-markdown`, `example-jaccard` and so on, so they
never replace the default ones:

```
logfold analyze examples/logfold-example-plugin/samples/app.logfmt --format example-logfmt
logfold diff before.logfmt after.logfmt --format example-logfmt --matcher example-jaccard
```

```python
result = logfold.analyze("app.logfmt", format="example-logfmt")
print(result.render("example-markdown", top=10))
```

## Your own plugins in a folder

No packaging is needed for a plugin that is only yours: put a Python file into the plugin folder and logfold loads it,
in the terminal as well as from Python.

```
logfold plugins dir                    # where logfold looks, and whether the folder exists
logfold plugins new format my-fmt      # writes a working template there: also `reporter` and `matcher`
```

The folder is `%APPDATA%\logfold\plugins` on Windows and `$XDG_CONFIG_HOME/logfold/plugins` (usually
`~/.config/logfold/plugins`) elsewhere. `logfold plugins new KIND NAME` creates `NAME.py` in it (it never overwrites
without `--force`; `--dir` writes somewhere else). Edit the file, then run `logfold plugins list`: the plugin is there,
and its source is the path of the file.

A plugin file lists what it provides in three module-level lists, all optional:

```python
from logfold.ext import RegexFormat


class Shout:  # a reporter: name, kinds, render()
    name = "shout"
    kinds = ("analysis",)

    def render(self, result, **options):
        return "\n".join(t.text.upper() for t in result.top(5)) + "\n"


FORMATS = [
    RegexFormat(
        name="mine",
        pattern=r"^(?P<ts>\S+) (?P<lvl>\w+) (?P<msg>.*)$",
        message_group="msg",
        time_group="ts",
        level_group="lvl",
    )
]
REPORTERS = [Shout]  # classes are created without arguments; instances work too
MATCHERS = []  # diff matchers: objects with name and match()
```

A folder with an `__init__.py` is loaded as a package, so a bigger plugin can have several files and relative imports.
Files and folders whose names start with `_` or `.` are skipped, as is everything that is not Python. Plugins are
loaded in alphabetical order, after the installed plugin packages; if two use the same name, the later one wins, so a
file in your folder can deliberately replace a default plugin (`logfold plugins list` shows which one is active).

More folders:

```
logfold --plugins-dir ./team-plugins analyze app.log --format mine      # for one run, repeatable
```

`LOGFOLD_PLUGIN_PATH` takes more folders for every run (separated like `PATH`), and from Python
`logfold.ext.add_plugin_directory(path)` loads one on the spot.

**Safety.** A plugin file is Python code that runs with your privileges when logfold starts to look up a format, a
reporter or a matcher (not for `--version` or `--help`). That is why logfold only reads folders you named or your own
config folder, never the current directory, so running logfold inside a downloaded project does not execute anything
from it. On Linux and macOS a folder or file that everybody can write to, or that belongs to another user, is skipped
with a warning. A broken file is skipped with a warning and never stops logfold. `LOGFOLD_NO_USER_PLUGINS=1` switches
off the config folder and `LOGFOLD_PLUGIN_PATH` (use it in CI and on shared machines); a folder passed with
`--plugins-dir` is your explicit choice and still loads.

## Writing a plugin

A plugin is either a file in your plugin folder (see above) or a package that you install; the contracts are the same.
A package is the way to share a plugin.

### Package layout

```
my-logfold-plugin/
  pyproject.toml
  my_plugin/
    __init__.py
```

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "my-logfold-plugin"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["logfold>=0.1.0"]

[project.entry-points."logfold.formats"]
logfmt = "my_plugin:LOGFMT"

[project.entry-points."logfold.reporters"]
csv = "my_plugin:CsvReporter"

[project.entry-points."logfold.matchers"]
jaccard = "my_plugin:JaccardMatcher"
```

Each line is `name = "module:attribute"`. The attribute can be:

- the object itself (a format specification, or a reporter or matcher instance);
- a class: logfold creates one instance without arguments;
- a function without arguments that returns the object.

A format is registered under the entry point **name**; keep it equal to the `name` of the specification. A reporter or
a matcher is registered under its `name` attribute. Registering a name twice replaces the earlier registration, so a
plugin can override a built-in name; avoid that. A plugin that fails to import is skipped with a warning
(`failed to load logfold plugin ...`, printed to standard error) and never breaks logfold.

### A format

A format is **data, not code**. You describe the format; the engine compiles the description into a fast parser, so the
plugin costs nothing per line and works the same in the Rust and the Python engine. There are three specifications,
all in `logfold.ext`.

`RegexFormat`: a regular expression with named groups. It is searched in the first line of a record, so anchor it with
`^`.

```python
from logfold.ext import RegexFormat

LOGFMT = RegexFormat(
    name="logfmt",
    pattern=r"^ts=(?P<ts>\S+) level=(?P<lvl>\w+) (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
)
```

| Field | Meaning |
|---|---|
| `pattern` | regular expression with named groups |
| `message_group` | group with the message; without it the whole first line is the message |
| `time_group`, `ts_format` | group with the timestamp and its `strptime`-style format; ISO-8601 when `ts_format` is omitted |
| `level_group` | group with the level; TRACE, DEBUG, INFO, WARN, ERROR and FATAL (and common spellings such as `warning`) are recognized, other values give no level |
| `multiline` | join lines that do not match `pattern` to the previous record (stack traces) |

`ts_format` understands `%Y %y %m %d %e %H %M %S %f %z %b %B %j %T %%`; any other character must match literally.
Timestamps without a zone are read as UTC.

`JsonFormat`: one JSON object per line. Give the candidate keys; the first key present wins.

```python
from logfold.ext import JsonFormat

SERILOG_CLEF = JsonFormat(
    name="serilog-clef",
    message_keys=("@m", "@mt"),
    time_keys=("@t",),
    level_keys=("@l",),
)
```

`PlainFormat`: the whole line is the message. With `record_start` and `multiline` it groups lines into records.

```python
from logfold.ext import PlainFormat

CI_BLOCKS = PlainFormat(name="ci-blocks", record_start=r"^=== ", multiline=True)
```

Invalid specifications (a bad regular expression, a group that does not exist, `multiline` without `record_start`)
raise `FormatError` when the object is created, so a mistake shows up on import.

For a one-off format you do not need a plugin: `--format "regex:<pattern>"` takes a pattern with the same named groups
(`message`/`msg`, `timestamp`/`ts`/`time`, `level`/`lvl`).

### A reporter

A reporter turns a result into text. It sees only the public result model ([API reference](api.md#results)), never the
engine.

```python
from logfold import AnalysisResult, DiffResult


class CsvReporter:
    name = "csv"
    kinds = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str: ...
```

| Member | Meaning |
|---|---|
| `name` | the name used in `result.render(name)` |
| `kinds` | `"analysis"`, `"diff"` or both; `render` is called only for these kinds |
| `render(result, **options)` | returns the document as text; `options` are whatever the caller passes (`top=10`) |

Tell `AnalysisResult` and `DiffResult` apart with `isinstance(result, DiffResult)`. Log lines are untrusted input:
templates and examples can contain markup, so escape them for the format you produce (the built-in HTML reporter
escapes everything; the CSV reporter relies on the `csv` module's quoting). For text that people read in a terminal, pass
values taken from a log through `logfold.ext.printable`, which shows control characters (escape sequences, bell) as `\xNN`
instead of letting them reach the terminal; the built-in `text`, `markdown`, `csv` and `html` reporters do.

### A diff matcher

`diff` mines both runs into one shared template tree, so templates present in both runs are matched by logfold itself.
A matcher only sees the rest: the template texts present in a single run.

```python
from collections.abc import Sequence


class JaccardMatcher:
    name = "jaccard"

    def match(self, before_only: Sequence[str], after_only: Sequence[str]) -> list[tuple[int, int]]: ...
```

`match` returns pairs `(i, j)` meaning `before_only[i]` and `after_only[j]` describe the same event. Every index may
occur at most once. The lists are short (only templates that changed between runs), so a simple quadratic comparison is
fine. A matcher is created without arguments; for a tunable one, subclass it and register the subclass.

### Without packaging

For a script or a notebook, register the objects at runtime. Nothing needs to be installed:

```python
from logfold.ext import register_format, register_matcher, register_reporter

register_format("logfmt", LOGFMT)
register_reporter(CsvReporter())
register_matcher(JaccardMatcher())
```

### Testing

Test a plugin without installing it. Format specifications can be passed to `analyze` directly, reporters and matchers
are plain objects:

```python
def test_logfmt():
    result = logfold.analyze("samples/app.logfmt", format=LOGFMT, engine="python")
    assert {t.text: t.count for t in result.templates} == {...}


def test_matcher_changes_the_diff(monkeypatch):
    register_matcher(JaccardMatcher())
    paired = logfold.diff("before.logfmt", "after.logfmt", format=LOGFMT, matcher="jaccard")
    assert not paired.new_templates
```

Run a format with both `engine="native"` and `engine="python"` and compare: they must give the same templates. The
example package does this, see [`tests/test_example_plugin.py`](../tests/test_example_plugin.py). Also test that every
entry point in `pyproject.toml` resolves to an existing attribute.

### Publishing

Build and upload like any Python package (`python -m build`, then `twine upload dist/*`). Name it
`logfold-<something>`, depend on `logfold>=0.1.0`, and state in your README which logfold versions you tested.

## Troubleshooting

| Symptom | Check |
|---|---|
| the format is not in `logfold formats` | the package is installed in **the same environment** as the `logfold` you run (`python -m pip list`); the entry point group is spelled `logfold.formats`; reinstall after changing `pyproject.toml` |
| `unknown format 'x'; known formats: ...` | the entry point name, not the module name, is the format name |
| `failed to load logfold plugin ...` on stderr | the module of the entry point cannot be imported; the traceback follows the message |
| `FormatError: pattern has no named group` | `message_group`, `time_group` or `level_group` names a group that the pattern does not define |
| the timestamp column is empty | the `time_group` text does not match `ts_format`; try the pattern and the format on one line first |
| my file in the plugin folder is not listed | `logfold plugins dir` shows the folder; the file must end in `.py`, must not start with `_` or `.`, and `FORMATS`, `REPORTERS` or `MATCHERS` must be lists; warnings explain the rest (a world-writable file is skipped, `LOGFOLD_NO_USER_PLUGINS` is set) |
| `logfold plugins install` says that neither pip nor uv is available | the environment has no installer on the path; install the printed package with the one you use |
| `logfold plugins install` says that the plugin needs logfold X.Y.Z or newer | the catalog entry sets `min_logfold`; upgrade logfold (`pip install -U logfold`) and try again |
| `reporter 'x' does not support diff results` | add `"diff"` to the reporter's `kinds` and handle `DiffResult` |

## Security

A plugin is Python code and runs with your privileges as soon as logfold loads it (reporters and matchers on import and
use, formats on import). Install plugins only from sources you trust. A format specification is data and cannot run
code, but a pattern that backtracks badly can be slow in the pure-Python engine (the Rust engine matches in linear
time); keep patterns anchored and simple.
