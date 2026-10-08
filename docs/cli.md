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
| `--format`, `-f` | `auto` | `auto`, a name from `logfold formats`, `regex:<pattern>`, or `log4j:<pattern>` |
| `--multiline` / `--no-multiline` | format default | join continuation lines (stack traces) to the previous record |
| `--since` TIME, `--until` TIME | | only records at or after / before this time (ISO 8601, for example `2026-10-06T12:00`; a trailing `Z` or an offset is a zone). A time without a zone is compared with the times of the log as written. Records without a time are left out and counted; needs a format with a time |
| `--top`, `-n` | 20 | rows printed per table |
| `--min-count` | 1 | hide templates with fewer records |
| `--level` | | keep templates whose most severe level is at least this (`TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL`; any case) |
| `--only-alerts` | off | same as `--level WARN`; not together with `--level` |
| `--out`, `-o` | | write a report; the suffix selects the format: `.html`/`.htm`, `.json`, `.txt` (plain text), `.md` (Markdown), `.csv`, `.xml` (JUnit, diff only) or `.prom` (Prometheus); `--report github-summary` and `--report chat-message` have no suffix |
| `--append` | off | add the `--out` report to the end of the file instead of replacing it, after a blank line (needs `--out`; text, Markdown, `github-summary` and `chat-message` reports, not `html`, `json`, `csv`, `junit` or `prometheus`); for `$GITHUB_STEP_SUMMARY` and other files several steps write to, see [CI](ci.md) |
| `--report` | | reporter by name (`logfold plugins list`, for example a plugin reporter): with `--out` it replaces the suffix's choice, without `--out` its text is printed instead of the tables; not with `--json` |
| `--json` | off | print JSON to standard output instead of tables |
| `--examples` | `raw` | `raw`, `masked` or `none`: how example messages are kept (use `masked` or `none` before sharing) |
| `--load-state` FILE | | continue from the miner that an earlier run saved (see [State files](#state-files)); the report counts only this run |
| `--save-state` FILE | | save the trained miner for a later run (templates and counts, no example lines); a `.gz` path is compressed |
| `--state-format` | `json` | `json` (readable) or `binary` (compact, for states of hundreds of thousands of templates) |
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
| `--strategy` | `auto` | `auto`, `sequential` (one tree) or `chunked` (parallel); `auto` chunks above 64 MiB, but mines sequentially when the first chunk shows that almost every record is a new template |
| `--threads` | all cores | worker threads of the chunked strategy |
| `--chunk-mb` | 64 | chunk size in MiB of the chunked strategy |
| `--warm-start` | off | chunked strategy: train the first chunk alone and start every other chunk from a copy of its tree; fewer stray templates, a serial prefix of one chunk (see the guide) |

### State files

A run can save what it learned and the next run can continue from it, so that a baseline is a small file and no log is read
twice:

```
logfold analyze monday.log --save-state model.json
logfold analyze tuesday.log --load-state model.json --save-state model.json
```

The second run reports only the records of `tuesday.log`, and `model.json` then holds both days: the same file as `analyze
monday.log tuesday.log --save-state ...` would have written. A state holds the templates (after masking: a template seen once is
its line with the values replaced), the shape of the tree and counts by level and time, never an example message. It must be
used with the same masks and parameters (`--depth`, `--sim-th`, `--max-children`, `--max-templates`, `--no-masks`); otherwise
the run stops with an error that says so. Continuing is sequential (`--strategy chunked` is refused, `auto` mines
sequentially), and needs the native engine. The size of a state depends on the number of templates (kilobytes for a
typical application; for 100 thousand templates about 12 MB in JSON at the least, since real templates are longer than the
short ones of that measurement, and about half of it in binary), not on the size of the logs. Treat a state like
a report of the templates: a template seen once contains the words of its line.

## `logfold diff`

Compare two runs: new, disappeared and changed templates. Shares are normalized by the number of records in each run.
A template is `changed` when its share moved by `--threshold-ratio`, it has `--min-count` records in either run, and the
move is statistically significant: a G-test of the template against all other records, before against after, gives
a p-value of at most `--significance`. The `changed` table is sorted by that score, largest first, and shows the `p`
value. Gates and exit codes look at new templates only, so they do not depend on this.

```
logfold diff BEFORE AFTER [options]
logfold diff LOG --split-at TIME [options]
logfold diff BEFORE AFTER --baseline MORE.log [--baseline ...] [options]
```

`BEFORE` and `AFTER` are single log files (for example before and after a deploy, or a passing and a failing CI job)
or two saved reports of `logfold analyze --out result.json`; both must be of one kind.

With `--baseline FILE` (repeatable) the first argument is the first baseline and each option adds one: the baselines
are pooled, so a template is `new` only if none of them has it, and `disappeared` or `changed` only if it occurs in at
least `--min-baselines` of them (default all). A template seen in some baselines but fewer than that is unstable and is
reported as nothing. It works with log files only, not with saved reports or `--split-at`. Every baseline is read in
full, so time and memory grow with their number; 3 to 5 recent good runs are usually enough, and more than 10 give a
warning.

With `--split-at TIME` give **one** log: the records before `TIME` are the first run and the records from `TIME` on are
the second, for example the hour before an incident against the hour after it. `--since` and `--until` bound the whole
range. The log is read once for each run and one template tree is shared, as for two files; the run names in the output
show the window. It needs a format with a time, a real file (not standard input) and does not work for saved reports.
`diff` accepts the same input, report, mining and execution options as `analyze` (`--min-count` has a different meaning,
see below), plus:

| Option | Default | Meaning |
|---|---|---|
| `--threshold-ratio` | 2.0 | factor by which a template's share must change to be reported as `changed` (at least 1) |
| `--min-count` | 10 | records, in either run, needed to report `changed` |
| `--min-new-count` | 1 | records needed to report a template as new or disappeared |
| `--baseline FILE` | none | another baseline log besides `BEFORE`; repeat it for more |
| `--min-baselines N` | all | with `--baseline`, the number of baselines a template must occur in to be reported as disappeared or changed |
| `--significance` | 0.01 | highest p-value of a `changed` template that is still reported (0 < P <= 1); `1` keeps every template that passes the ratio and count thresholds |
| `--matcher` | `jaccard` | `jaccard`, `jaccard-idf`, `overlap`, `token_subset`, `exact` or `rules:FILE` (your own pairs); plugins add more ([how to choose](guide.md#choosing-a-matcher)) |
| `--recount` / `--no-recount` | on | assign every record to the finished template tree; `--no-recount` is faster but can show spurious differences |
| `--fail-on-new` | off | exit with code 2 when new templates are found |
| `--fail-on-new-alerts` | off | exit with code 2 when new templates with level WARN, ERROR or FATAL are found |

```
logfold diff before.log after.log --out diff.html --fail-on-new-alerts
```

The gates count *new* templates only. A template that the matcher pairs with an older one (a reworded message) is reported as
`changed`, not as new, so it does not trip a gate. Use `--matcher exact` when the gate must fail on every text that did not
exist before.

With saved reports the logs are not read again, so `diff` is instant and the logs may be gone:

```
logfold analyze before.log --out before.json
logfold analyze after.log --out after.json
logfold diff before.json after.json
```

The two analyses are mined separately and are not re-counted against a shared tree, so the matcher (`jaccard` by
default) pairs templates that describe one event. The format, mining and execution options and `--no-recount` are an error in this
mode. `--examples none` drops the saved examples and `--examples masked` is an error: the examples stay as they were
saved, so use `--examples masked` or `none` when analyzing. Write the reports with `--out`: a PowerShell 5 `>`
redirect saves UTF-16, which is refused. `--min-count` hides rare templates from the tables and text reports, but a
`.json` file written with `--out` always holds every template; `--json` on stdout follows `--min-count`, so do not use
it for reports you will compare.

`--level` and `--only-alerts` work the same way in both commands. A template's level is the most severe level among its
records, so `--level ERROR` keeps a template that has even one ERROR record. In `analyze` they filter the tables and the
reports like `--min-count` does (a `.json` file from `--out` stays complete) and a note on standard error says how many
templates were hidden. In `diff` they filter the new, disappeared and changed lists, every report and the gates: `--fail-on-new
--level ERROR` exits with code 2 only when a new template at ERROR or above exists. A format without levels (nginx, apache,
plain) is an error with a hint, not an empty result.

## `logfold inspect`

```
logfold inspect FILE [--format F] [--multiline/--no-multiline] [-n N] [--sample-lines N] [--json]
```

Shows how a file is read, without mining it: the detected (or given) format and its confidence, whether multiline is on, the
first records as parsed (time, level, message; `(+N lines)` marks a joined stack trace), and from a sample of the start of
the file the level counts, the time range and the number of lines that did not parse. Use it to check a format before
`analyze`, and to see why `--level` finds nothing.

| Option | Default | Meaning |
|---|---|---|
| `--format`, `-f` | `auto` | as in `analyze` |
| `--multiline` / `--no-multiline` | format default | as in `analyze` |
| `--records`, `-n` | 10 | records to show |
| `--sample-lines` | 1000 | non-blank lines read for the counts and the time range |
| `--json` | off | print JSON (`kind: inspection`, `schema_version: 1`) instead of text |

Only the start of the file is read, so it is quick on any size; gzip is detected by content. Standard input is not
supported (save a sample with `head -n 1000`). A hint is printed when more than a tenth of the sampled lines did not parse
or when the format has no levels.

## `logfold formats`

Lists the available log formats (built-in and plugins) with their kind and details, then the format plugins of the
catalog that are not installed yet with their install command. See the [formats table](guide.md#formats).

When a format, reporter or matcher name is not found, the error's `hint:` line names the plugin of the catalog with that
name (and how to install it) or the closest installed or catalog name. The `--help` of `analyze`, `diff` and `inspect`
lists the plugins available to install next to `--format`, `--report` and `--matcher`. The catalog is read only for these
messages and for `--help`; a normal run never touches it.

## `logfold info`

Prints the logfold and Python versions, whether the native engine is available (with its core, contract and algorithm
versions), and the registered formats and reporters. Include its output in bug reports.

## `logfold plugins`

List, check and install plugins (formats, reporters, diff matchers). See the [plugins guide](plugins.md).

```
logfold plugins list [--installed | --available] [--kind KIND] [--online] [--catalog SOURCE] [--json]
logfold plugins info NAME [--kind KIND] [--online] [--catalog SOURCE] [--json]
logfold plugins check [--online] [--catalog SOURCE] [--json]
logfold plugins install NAME [--online] [--catalog SOURCE] [--yes]
logfold plugins dir
logfold plugins new KIND NAME [--dir FOLDER] [--force]
```

| Command | What it does |
|---|---|
| `list` | every format, reporter and diff matcher with its status: `built-in`, `installed` (a package or a file in your plugin folder) or `available` (in the catalog, not installed), and the package that provides it |
| `info NAME` | one plugin: what it does, where it comes from, how to install it (available) or use it (installed), for every kind that has this name |
| `check` | the plugins of the catalog whose package is not installed yet, with an install hint |
| `install NAME` | shows the package, version constraint and catalog, asks for confirmation and runs `python -m pip install` (or `uv pip install` when the environment has no pip) for a plugin of the catalog; a plugin that needs a newer logfold (`min_logfold`) is refused before the question |
| `dir` | where logfold looks for your own plugin files, and whether that folder exists |
| `new KIND NAME` | writes a working plugin template (`format`, `reporter` or `matcher`) into the plugin folder; `--dir` chooses another folder, `--force` overwrites |

| Option | Default | Meaning |
|---|---|---|
| `--online` | off | fetch the latest catalog over HTTPS instead of using the one bundled with logfold |
| `--catalog` | | a catalog file or an HTTPS URL; overrides `--online` |
| `--installed` | off | `list`: only what is built in or installed |
| `--available` | off | `list`: only the catalog plugins that are not installed |
| `--kind`, `-k` | | `list`, `info`: only `format`, `reporter` or `matcher` |
| `--json` | off | print JSON instead of a table (`list`, `info`, `check`) |
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

Errors are printed on standard error as `error: ...`, followed by a `hint: ...` line when there is a next step: the
closest known name for a misspelled format, reporter or diff matcher (`did you mean 'nginx'?`) with the command that lists
them, the options to try when the format cannot be detected (`-f plain`, `-f regex:<pattern>`), the accepted suffixes for an
`--out` file without one, and the valid values of `--engine` and `--strategy`. Long paths are not wrapped at the terminal
width. `--debug` shows the traceback instead.

## Output and environment

- On a terminal the result is printed as tables. When standard output is not a terminal, the plain-text report is
  written instead, so the output can be piped. `--json` always prints JSON.
- Progress is shown on standard error only on a terminal and never with `--quiet`; it shows the bytes read, the speed and the
  elapsed time.
- Colors follow the terminal: set `NO_COLOR=1` to switch them off. The `analyze` summary has a `levels:` line, and the line
  under the table says how many templates it hides, what share of the records they cover and how to see them.
- A written HTML report is announced as `wrote report.html  (open it in a browser)`.
- `logfold analyze --help` and `logfold diff --help` group the options into the panels Input, Output, Diff (`diff` only),
  Mining, Execution and General, and end with usage examples.
- `--warm-start` and `--chunk-mb` only matter for the chunked strategy. When the run turned out sequential (a small input
  with `--strategy auto`, `--strategy sequential`, `--high-cardinality`, or the python engine) the result's warnings say that
  `warm_start` was ignored, and for the last three also `chunk_bytes`, and they are printed with the other warnings; the exit code does not change.
- `LOGFOLD_ENGINE=auto|native|python` selects the engine when `--engine` is not given. `python` forces the slow
  reference engine.
- `LOGFOLD_OFFLINE=1` forbids the network access of `logfold plugins check|install --online` and `--catalog URL`.
- `LOGFOLD_PLUGIN_PATH` adds plugin folders (separated like `PATH`); `LOGFOLD_NO_USER_PLUGINS=1` switches off the
  plugin folder and `LOGFOLD_PLUGIN_PATH`.
