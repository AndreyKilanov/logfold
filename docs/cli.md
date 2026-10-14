# Command-line reference

```
logfold [--version] <command> [options]
```

Commands: [`analyze`](#logfold-analyze), [`match`](#logfold-match), [`stream`](#logfold-stream), [`diff`](#logfold-diff),
[`params`](#logfold-params), [`inspect`](#logfold-inspect), [`formats`](#logfold-formats), [`info`](#logfold-info), [`plugins`](#logfold-plugins). Install the command with `pip install "logfold[cli]"`.

`logfold --version` prints the version. `logfold <command> --help` prints the options of a command.

**Settings file.** `analyze`, `match`, `stream`, `diff`, `params` and `inspect` read a [`logfold.toml`](config.md) for the options that you
do not give: `logfold --config FILE <command>` names the file, `logfold --no-config <command>` reads none, and without
either the first `logfold.toml` from the current folder up to the repository root is used. A flag beats the file; the
file beats the built-in default. A command that uses a file says so on standard error.

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
| `--save-state` FILE | | save the trained miner for a later run (templates and counts, no example lines); a `.gz` path is compressed (a gzip state is read by its content, whatever its name) |
| `--state-format` | `json` | `json` (readable) or `binary` (compact, for states of hundreds of thousands of templates) |
| `--quiet`, `-q` | off | no progress and no status messages on standard error |
| `--debug` | off | show tracebacks |

Mining and execution options, shared with `diff`:

| Option | Default | Meaning |
|---|---|---|
| `--depth` | 4 | template tree depth, at least 3 |
| `--sim-th` | 0.4 | similarity threshold in `[0, 1]` |
| `--max-children` | 100 | children per tree node |
| `--max-templates` | 100000 | template cap; what happens to further records is decided by `--on-full` |
| `--delimiters` | space, tab, CR, LF | the characters that separate tokens, **replacing** the default; `\t`, `\n`, `\r` and `\\` are read as escapes, so `--delimiters ' \t\n\r_='` also splits at `_` and `=` (keep the whitespace). A state must be used with the same value; `logfold params` needs the space among them |
| `--on-full` | `pool` | at the cap: `pool` puts the records of a new message shape into catch-all templates, `evict` drops the least recently used templates (a tenth of the cap at a time) and keeps learning; their counts join the catch-all templates, `run.evicted` and a warning say how many were dropped. It mines with one tree, so `--strategy chunked` is refused; a state must be used with the same value |
| `--masks` | none | mask sets that run **before** the default masks, comma-separated: `--masks secrets,pii`; `logfold masks list` shows what is installed. A state must be used with the same sets (see [Mask sets](#mask-sets)) |
| `--masks-file` | none | a mask set from a JSON file (repeat the flag for several); it runs after the sets of `--masks` |
| `--no-masks` | off | do not mask numbers, IPs, UUIDs and other values; cannot be combined with `--masks` or `--masks-file` |
| `--high-cardinality` | off | fast bounded mode for data with a huge number of distinct messages (5000 templates, sequential) |
| `--engine` | `auto` | `auto` or `native`; `python` is deprecated and runs `native` |
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
used with the same masks and parameters (`--depth`, `--sim-th`, `--max-children`, `--max-templates`, `--on-full`, `--delimiters`, `--no-masks`); otherwise
the run stops with an error that says so. Continuing needs the native engine. An input of more than one chunk (64 MiB by default,
`--chunk-mb`) is continued **in parallel** by default: every chunk starts from a copy of the loaded tree, the result does not
depend on the number of threads and, on six of seven 100 MB logs, has exactly the templates of the sequential run, 3 to 5 times
faster; on a log of many rare messages (Thunderbird) it has more than twice the templates, in 0.5 percent of the records
(`bench/docs/STATE_PARALLEL.md`), and a warning says that the continuation was parallel. `--strategy sequential` is the exact
continuation: the same state as one run over both logs. A smaller input is continued in one piece. The size of a state depends on the number of templates (kilobytes for a
typical application; for 100 thousand templates about 12 MB in JSON at the least, since real templates are longer than the
short ones of that measurement, and about half of it in binary), not on the size of the logs. Treat a state like
a report of the templates: a template seen once contains the words of its line.

## `logfold match`

```
logfold match STATE FILE... [options]
```

Assigns the records of FILES (one run; `-` reads standard input) to the templates of a state that `logfold analyze
--save-state` wrote, and counts the records that fit none. Nothing is learned and the state file is only read:

```
logfold analyze baseline.log --save-state model.json
logfold match model.json today.log
```

The report is the one of `analyze`: the templates of the state that were hit, with the counts, levels and times of
`today.log` only. A warning says how many records belong to no template of the state, and `run.unmatched` in the JSON report
holds their number and their length in tokens (the text of those records is not kept). The state must be used with the same
masks and parameters it was mined with (`--depth`, `--sim-th`, `--max-children`, `--max-templates`, `--on-full`, `--delimiters`, `--no-masks`); otherwise the
command stops with an error that says so. The result does not depend on `--strategy` or `--threads`, which only decide
whether the files are read in parallel.

A record belongs to a template when at least the share `--sim-th` of its words equals the constant words of the template, so a
record that differs from a template in one word still belongs to it. `--exact` asks for the strict meaning of Drain3: every
constant word of the template must equal the word of the record (a `<*>` accepts any word), otherwise the record counts as
belonging to none. Use it to find the records that no template describes exactly.

Options: `--format`, `--multiline`, `--since`, `--until`, `--top`, `--min-count`, `--level`, `--only-alerts`, `--out`,
`--append`, `--report`, `--json`, `--examples`, `--quiet`, `--debug` as for [`analyze`](#logfold-analyze), and the mining
and execution options listed there (`--sim-th`, `--depth`, `--max-children`, `--max-templates`, `--on-full`, `--delimiters`, `--no-masks`, `--strategy`,
`--threads`, `--chunk-mb`), and `--exact`. There is no `--save-state`, `--load-state`, `--high-cardinality`, `--warm-start` or `--engine`.

## `logfold stream`

```
logfold stream [FILE] [options]
```

Mines a log while it is written: reads FILE (standard input when it is missing or `-`), prints every template once, on a line
that starts with `new`, when it first appears, and writes the usual report when the input ends:

```
kubectl logs -f deploy/api | logfold stream --format plain
tail -F app.log | logfold stream -f app --save-state model.json --save-every 60
```

The result is the one of `logfold analyze` over the same lines, whatever the batch size. A line is read as soon as it
arrives; `--batch-size` (1000) is the most lines mined in one step, and a quiet stream is mined after a second. The text
of a template is the one it had when it was created, with control characters shown instead of acted on.

The format is `plain` unless `--format` names another one; `auto` is refused, because a stream has no file to detect it
from. With a multi-line format a record is mined when the next record starts, or after a second of silence. Bytes that are
not UTF-8 become U+FFFD, a line longer than 1 Mi characters is read in pieces, and the lines that wait for the miner never
take more than about 16 million characters. On a 105 MB file it mines about 94 MB/s, 1.4 times the time of `analyze`
(`bench/docs/STREAM.md`).

`--load-state FILE` continues from a state of `analyze`, `match` or an earlier `stream` (the templates it holds are not
announced), `--save-state FILE` writes the state at the end, and `--save-every SECONDS` writes it while the stream runs too
(the old file stays until the new one is complete). Ctrl+C ends the input: the state is saved, the report is written for what
was read, and the exit code is 130.

Options: `--format`, `--multiline`, `--top`, `--level`, `--only-alerts`, `--out`, `--append`, `--report`, `--json`,
`--examples`, `--quiet`, `--debug`, `--state-format` as for [`analyze`](#logfold-analyze), and `--sim-th`, `--depth`,
`--max-children`, `--max-templates`, `--on-full`, `--delimiters`, `--no-masks`. With `--json`, or `--report` without `--out`, the `new`
lines are not printed, so that standard output holds only the report. There is no `--since`, `--until`, `--strategy` or
`--threads`: a stream is mined by one tree, in the order it arrives.

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

## `logfold params`

```
logfold params TEMPLATE MESSAGE [--no-masks] [--delimiters CHARS] [--json]
```

Prints the values that one MESSAGE has at the variable parts of a TEMPLATE, one per line as `position`, the name of the masking
rule or `*` (a position the miner generalized), and the value as it was written in the message:

```
$ logfold params "user <NUM> logged in from <IP>" "user 42 logged in from 10.0.0.1:8080"
1	num	42
5	ip	10.0.0.1:8080
```

Copy TEMPLATE from a report and MESSAGE from the log. The message is masked and tokenized as the miner does, so it needs the
masks that the template was mined with: `--no-masks` for a run mined without them, and the masks of a `logfold.toml` apply as for
the other commands. With `--json` the output is `{"parameters": [{"position": 1, "name": "num", "value": "42"}]}`. A message that
does not fit the template (another number of tokens, or a constant token that differs) is an error with exit code 1 and a hint.
A message that starts with a dash needs `--` before the arguments. Control characters of a value are shown as hexadecimal escapes
instead of being acted on. The same is available in Python as
[`logfold.extract_parameters`](api.md#extract_parameters).

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

## Mask sets

A mask set is a named list of masking rules that hides a kind of value before the log is mined, so that the templates, the
saved state and the report never hold it. Two sets ship with logfold:

| Set | Hides | Token |
|---|---|---|
| `secrets` | JWTs, `Authorization` headers and `Bearer` tokens, API keys with a known prefix (AWS, GitHub, GitLab, Slack, Stripe, Google, npm, SendGrid, `sk-`), passwords and tokens in URLs and in `password=`, `token=`, `api_key=` pairs, private keys | `<JWT>`, `<KEY>`, `<SECRET>` |
| `pii` | e-mail addresses, international phone numbers (`+44 20 7946 0958`), payment card numbers (the Luhn check) and IBANs (the mod-97 check) | `<EMAIL>`, `<PHONE>`, `<CARD>`, `<IBAN>` |

```
logfold analyze app.log --masks secrets,pii --examples masked
logfold analyze app.log --masks-file ./orders.json --save-state model.json
logfold masks list
logfold masks show secrets
```

The rules of the chosen sets run first, in the order given, and the default masks (numbers, IPs, UUIDs, timestamps, paths,
hex values) run last over the text that is left, so a card number is `<CARD>` and not four `<NUM>`. A rule may carry a check
(`luhn` or `iban`): a match that fails it is not masked, so a long number that is not a card stays a number. Rules are
regular expressions of a linear-time engine; no rule is code.

* `--masks-file FILE` reads a set from a JSON file ([schema](schema/mask-set.schema.json), at most 1 MiB, 256 rules, 4 KiB
  per pattern); `[mining] masks = ["secrets", "pii"]` in [`logfold.toml`](config.md) names sets; a plugin package can ship
  sets (see [plugins](plugins.md#mask-sets)). A flag beats the file.
* A state is tied to the exact rules it was mined with: another set, another version of a set or another order is refused
  with `StateError`. `logfold masks show NAME` prints the fingerprint that the state header keeps.
* The sets hide values in templates and states. **The examples of a report are still the raw lines** unless you choose
  `--examples masked` or `none`; a run that selects sets with raw examples says so on standard error.
* The sets lower the risk and do not remove it: a rule finds what it can describe (a prefix, a label, a checksum), not a
  random password without a label, and it can mask something that only looks like a secret (the word `token` followed by a
  long value). `bench/docs/MASK_SETS.md` lists what they changed on 16 public logs and what they cost: about 17 to 20% of the
  time of a run on 100 MB logs without secrets.
* `logfold masks list [--json]` shows the sets that `--masks` accepts, `logfold masks show NAME_OR_FILE [--json]` the rules
  of one.

## `logfold info`

Prints the logfold and Python versions, whether the native engine is available (with its core, contract and algorithm
versions), and the registered formats, reporters, matchers and mask sets. Include its output in bug reports.

## `logfold plugins`

List, check and install plugins (formats, reporters, diff matchers, mask sets). See the [plugins guide](plugins.md).

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
| `list` | every format, reporter, diff matcher and mask set with its status: `built-in`, `installed` (a package or a file in your plugin folder) or `available` (in the catalog, not installed), and the package that provides it |
| `info NAME` | one plugin: what it does, where it comes from, how to install it (available) or use it (installed), for every kind that has this name |
| `check` | the plugins of the catalog whose package is not installed yet, with an install hint |
| `install NAME` | shows the package, version constraint and catalog, asks for confirmation and runs `python -m pip install` (or `uv pip install` when the environment has no pip) for a plugin of the catalog; a plugin that needs a newer logfold (`min_logfold`) is refused before the question |
| `dir` | where logfold looks for your own plugin files, and whether that folder exists |
| `new KIND NAME` | writes a working plugin template (`format`, `reporter`, `matcher` or `mask`) into the plugin folder; `--dir` chooses another folder, `--force` overwrites |

| Option | Default | Meaning |
|---|---|---|
| `--online` | off | fetch the latest catalog over HTTPS instead of using the one bundled with logfold |
| `--catalog` | | a catalog file or an HTTPS URL; overrides `--online` |
| `--installed` | off | `list`: only what is built in or installed |
| `--available` | off | `list`: only the catalog plugins that are not installed |
| `--kind`, `-k` | | `list`, `info`: only `format`, `reporter`, `matcher` or `mask` |
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
| 130 | interrupted (Ctrl+C); `stream` first saves the state and writes the report for what it read |

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
  with `--strategy auto`, `--strategy sequential` or `--high-cardinality`) the result's warnings say that
  `warm_start` was ignored, and for the last two also `chunk_bytes`, and they are printed with the other warnings; the exit code does not change.
- `LOGFOLD_ENGINE=auto|native` selects the engine when `--engine` is not given. `python`, the name of the removed
  reference engine, still works: it runs the native engine with a deprecation warning.
- `LOGFOLD_OFFLINE=1` forbids the network access of `logfold plugins check|install --online` and `--catalog URL`.
- `LOGFOLD_PLUGIN_PATH` adds plugin folders (separated like `PATH`); `LOGFOLD_NO_USER_PLUGINS=1` switches off the
  plugin folder and `LOGFOLD_PLUGIN_PATH`.
