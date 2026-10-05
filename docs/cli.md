# Command-line reference

```
logfold [--version] <command> [options]
```

Commands: [`analyze`](#logfold-analyze), [`diff`](#logfold-diff), [`formats`](#logfold-formats),
[`info`](#logfold-info), [`plugins`](#logfold-plugins). Install the command with `pip install "logfold[cli]"`.

`logfold --version` prints the version. `logfold <command> --help` prints the options of a command.

## `logfold analyze`

Fold one run into message templates and count them.

```
logfold analyze FILES... [options]
```

`FILES` are one or more log files that form **a single run**; `-` reads standard input. Gzip files (also multi-member)
are detected by content, not by extension.

```
logfold analyze app.log --top 30 --out report.html
logfold analyze app.log --report csv > templates.csv
logfold analyze app.log --report markdown --out summary.txt
logfold analyze app.log.1.gz app.log --min-count 5
journalctl -o json | logfold analyze - --format journald --json > result.json
```

| Option | Default | Meaning |
|---|---|---|
| `--format`, `-f` | `auto` | `auto`, a name from `logfold formats`, or `regex:<pattern>` |
| `--multiline` / `--no-multiline` | format default | join continuation lines (stack traces) to the previous record |
| `--top`, `-n` | 20 | rows printed per table |
| `--min-count` | 1 | hide templates with fewer records |
| `--out`, `-o` | | write a report; the suffix selects the format: `.html`/`.htm`, `.json`, `.txt` (plain text), `.md` (Markdown) or `.csv` |
| `--report` | | reporter by name (`logfold plugins list`, for example a plugin reporter): with `--out` it replaces the suffix's choice, without `--out` its text is printed instead of the tables; not with `--json` |
| `--json` | off | print JSON to standard output instead of tables |
| `--examples` | `raw` | `raw`, `masked` or `none`: how example messages are kept (use `masked` or `none` before sharing) |
| `--quiet`, `-q` | off | no progress and no status messages on standard error |
| `--debug` | off | show tracebacks |

Mining and execution options, shared with `diff`:

| Option | Default | Meaning |
|---|---|---|
| `--depth` | 4 | template tree depth, at least 3 |
| `--sim-th` | 0.4 | similarity threshold in `[0, 1]` |
| `--max-children` | 100 | children per tree node |
| `--max-templates` | 100000 | template cap; further records are pooled into catch-all templates |
| `--no-masks` | off | do not mask numbers, IPs, UUIDs and other values |
| `--high-cardinality` | off | fast bounded mode for data with a huge number of distinct messages (5000 templates, sequential) |
| `--engine` | `auto` | `auto`, `native` or `python` (slow reference engine) |
| `--strategy` | `auto` | `auto`, `sequential` (one tree) or `chunked` (parallel); `auto` chunks above 64 MiB |
| `--threads` | all cores | worker threads of the chunked strategy |
| `--chunk-mb` | 64 | chunk size in MiB of the chunked strategy |

## `logfold diff`

Compare two runs: new, disappeared and changed templates. Shares are normalized by the number of records in each run.

```
logfold diff BEFORE AFTER [options]
```

`BEFORE` and `AFTER` are single log files (for example before and after a deploy, or a passing and a failing CI job)
or two saved reports of `logfold analyze --out result.json`; both must be of one kind.
`diff` accepts the same input, report, mining and execution options as `analyze` (`--min-count` has a different meaning,
see below), plus:

| Option | Default | Meaning |
|---|---|---|
| `--threshold-ratio` | 2.0 | factor by which a template's share must change to be reported as `changed` (at least 1) |
| `--min-count` | 10 | records, in either run, needed to report `changed` |
| `--min-new-count` | 1 | records needed to report a template as new or disappeared |
| `--matcher` | `exact` | `exact` or `token_subset`; plugins add more |
| `--recount` / `--no-recount` | on | assign every record to the finished template tree; `--no-recount` is faster but can show spurious differences |
| `--fail-on-new` | off | exit with code 2 when new templates are found |
| `--fail-on-new-alerts` | off | exit with code 2 when new templates with level WARN, ERROR or FATAL are found |

```
logfold diff before.log after.log --out diff.html --fail-on-new-alerts
```

With saved reports the logs are not read again, so `diff` is instant and the logs may be gone:

```
logfold analyze before.log --out before.json
logfold analyze after.log --out after.json
logfold diff before.json after.json --matcher token_subset
```

The two analyses are mined separately and are not re-counted against a shared tree, so use `--matcher token_subset` to
pair templates that describe one event. The format, mining and execution options and `--no-recount` are an error in this
mode. `--examples none` drops the saved examples and `--examples masked` is an error: the examples stay as they were
saved, so use `--examples masked` or `none` when analyzing. Write the reports with `--out`: a PowerShell 5 `>`
redirect saves UTF-16, which is refused. `--min-count` hides rare templates from the tables and text reports, but a
`.json` file written with `--out` always holds every template; `--json` on stdout follows `--min-count`, so do not use
it for reports you will compare.

## `logfold formats`

Lists the available log formats (built-in and plugins) with their kind and details. See the
[formats table](guide.md#formats).

## `logfold info`

Prints the logfold and Python versions, whether the native engine is available (with its core, contract and algorithm
versions), and the registered formats and reporters. Include its output in bug reports.

## `logfold plugins`

List, check and install plugins (formats, reporters, diff matchers). See the [plugins guide](plugins.md).

```
logfold plugins list [--json]
logfold plugins check [--online] [--catalog SOURCE] [--json]
logfold plugins install NAME [--online] [--catalog SOURCE] [--yes]
logfold plugins dir
logfold plugins new KIND NAME [--dir FOLDER] [--force]
```

| Command | What it does |
|---|---|
| `list` | every format, reporter and diff matcher with its source: `built-in` or the package that provides it |
| `check` | the plugins of the catalog whose package is not installed yet, with an install hint |
| `install NAME` | shows the package, version constraint and catalog, asks for confirmation and runs `python -m pip install` for a plugin of the catalog |
| `dir` | where logfold looks for your own plugin files, and whether that folder exists |
| `new KIND NAME` | writes a working plugin template (`format`, `reporter` or `matcher`) into the plugin folder; `--dir` chooses another folder, `--force` overwrites |

| Option | Default | Meaning |
|---|---|---|
| `--online` | off | fetch the latest catalog over HTTPS instead of using the one bundled with logfold |
| `--catalog` | | a catalog file or an HTTPS URL; overrides `--online` |
| `--json` | off | print JSON instead of a table (`list`, `check`) |
| `--yes`, `-y` | off | do not ask for confirmation (`install`) |

`logfold --plugins-dir FOLDER ...` (an option of `logfold` itself, repeatable) also loads the plugins of a folder; see
[your own plugins in a folder](plugins.md#your-own-plugins-in-a-folder).

Without `--online` and `--catalog` nothing is downloaded. `LOGFOLD_OFFLINE=1` makes every network access of these
commands an error. `install` accepts only names from the catalog; a declined confirmation, an unknown name, an invalid
catalog or a failed pip run exit with code 1.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | success |
| 1 | error: invalid option, unreadable input, unknown or undetected format, engine unavailable |
| 2 | `diff` with `--fail-on-new` found new templates, or with `--fail-on-new-alerts` found new WARN/ERROR/FATAL templates |
| 130 | interrupted (Ctrl+C) |

Errors are printed as one line on standard error; `--debug` adds the traceback.

## Output and environment

- On a terminal the result is printed as tables. When standard output is not a terminal, the plain-text report is
  written instead, so the output can be piped. `--json` always prints JSON.
- Progress is shown on standard error only on a terminal and never with `--quiet`.
- `LOGFOLD_ENGINE=auto|native|python` selects the engine when `--engine` is not given. `python` forces the slow
  reference engine.
- `LOGFOLD_OFFLINE=1` forbids the network access of `logfold plugins check|install --online` and `--catalog URL`.
- `LOGFOLD_PLUGIN_PATH` adds plugin folders (separated like `PATH`); `LOGFOLD_NO_USER_PLUGINS=1` switches off the
  plugin folder and `LOGFOLD_PLUGIN_PATH`.
