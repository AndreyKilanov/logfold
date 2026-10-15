# logfold guide

This guide walks through the typical tasks. For the complete lists of options and signatures see the
[command-line reference](cli.md) and the [Python API reference](api.md). If you use Drain3 now, start with
[Migrating from Drain3](migrating-from-drain3.md).

Three pages start from a situation instead of a command: [finding what changed in an incident](incident.md),
[sharing a log or a report safely](share-a-log.md) and [logfold in a Python program](python.md).

## Install

```
pip install "logfold[cli]"        # library, native engine and the `logfold` command
pipx install "logfold[cli]"       # just the command
```

The core library has no dependencies. The `cli` extra adds `typer` and `rich`. Python 3.11 or newer.

## Fold a log into templates

```python
from logfold import analyze

result = analyze("app.log")  # format is detected
for template in result.top(10):
    print(template.count, template.level, template.text)
result.to_html("report.html")  # self-contained, works offline
result.to_json("report.json")  # schema: docs/schema/analysis-v1.schema.json
```

```
logfold analyze app.log --top 20 --out report.html
```

Several files can form one run (`analyze(["app.log.1.gz", "app.log"])` in Python, `logfold analyze app.log.1.gz app.log`
on the command line), `-` reads standard input and gzip files are detected by content.

A template looks like `user <*> failed login from <IP>`: `<*>` is a variable part, `<IP>`, `<NUM>`, `<UUID>`, `<TS>`,
`<HEX>` and `<PATH>` are values replaced by the default masking rules before mining.

## Compare two runs

```python
from logfold import diff

d = diff("before.log", "after.log")
d.new_templates  # present after, absent before (most frequent first)
d.disappeared
d.changed  # share changed by at least threshold_ratio (default 2.0) and significantly (p <= 0.01); largest score first
d.new_alerts  # new templates whose most severe level is WARN or higher
d.to_html("diff.html")
```

```
logfold diff before.log after.log --out diff.html --fail-on-new
```

Exit codes: `0` success, `1` error, `2` new templates found with `--fail-on-new` (or new WARN/ERROR/FATAL templates
with `--fail-on-new-alerts`).

Shares are normalized by the number of records in each run, so runs of different size are comparable. Both runs are
mined into one shared template tree, and then **every record of both runs is assigned to the finished tree** (the
`recount` pass), so identical lines always land in the same template. `--no-recount` skips the second pass and is
faster but can show spurious differences.

### Compare two parts of one log

An incident often sits inside one file. Cut the log at a time and compare what came before with what came after:

```python
diff("app.log", split_at="2026-10-06T12:00")
diff("app.log", split_at="2026-10-06T12:00", since="2026-10-06T11:00", until="2026-10-06T13:00")  # an hour each side
```

```
logfold diff app.log --split-at 2026-10-06T12:00 --since 2026-10-06T11:00 --until 2026-10-06T13:00
```

`since` and `until` also work in `analyze` (`logfold analyze app.log --since ... --until ...`) to look at a part of a log.
Times are ISO 8601. A time with a zone is converted to UTC; a time without one is compared with the times in the log as
written. A record without a timestamp cannot be placed, so it is left out and counted (`run.untimed`); records outside
the window are counted in `run.out_of_range` and do not enter the shares.

### Compare with several baselines

A template missing from one good run may still be normal. Give `diff` more good runs and it reports as `new` only what
none of them has:

```python
diff("good1.log", "after.log", baselines=["good2.log", "good3.log"])
diff("good1.log", "after.log", baselines=["good2.log", "good3.log"], min_baselines=2)
```

```
logfold diff good1.log after.log --baseline good2.log --baseline good3.log --min-baselines 2
```

The baselines are mined with one template tree and pooled: counts and records add up, and shares are normalized by the
pooled records. By default a template must occur in every baseline to be reported as `disappeared` or `changed`;
`min_baselines` lowers that bar. A template that occurs in some baselines, but in fewer than the minimum, is unstable:
it is never reported as new, disappeared or changed. Baselines are logs only, not saved results or `--split-at`. Each baseline is read in full, so time and memory grow with
their number. Three to five recent good runs are enough to tell stable templates from noise; more than ten give a
warning.

### Compare the values

A template that exists in both runs can hide a change in its values (`added item <NUM> to the catalog` with new product numbers).
`--new-values` lists, for each variable position of the shared templates, the values that only the second run has and the values that only the first has:

```python
d = diff("before.log", "after.log", new_values=True)
for item in d.value_changes:
    for change in item.changes:
        print(item.text, change.name, change.new_distinct, "new", change.gone_distinct, "gone", change.new[:3])
```

```
logfold diff before.log after.log --new-values
```

It takes 1.5 to 3 times as long as a plain `diff`; memory is bounded, and a position with more than a million different
values is reported as not compared instead of a wrong list. Logs only, not saved results or `--baseline`. See [New and gone values](cli.md#new-and-gone-values).

### Compare saved results

Analyze each log once, keep the JSON, and compare the reports later without the logs:

```python
from logfold import analyze, diff, load_analysis

analyze("before.log").to_json("before.json")
analyze("after.log").to_json("after.json")
d = diff(load_analysis("before.json"), load_analysis("after.json"))
```

```
logfold diff before.json after.json
```

The reports were mined separately, with no shared tree and no `recount` pass, so the same event can appear as new in
one and disappeared in the other; a matcher pairs such templates, and a warning says so. Analyze both logs with the same
masks and parameters (the `config_hash` of the reports must match, or a warning is added). Examples are kept as saved:
choose `examples="masked"` or `"none"` when analyzing if they may hold sensitive values.

### Choosing a matcher

A template that exists in one run only can be paired with its closest counterpart, so a reworded message, or one that differs in
a host name, is compared as one template instead of being reported as one new and one disappeared template. The matcher decides
what counts as the same template: `--matcher NAME` on the command line, `matcher="NAME"` in Python.

| | `jaccard` (default) | `token_subset` | `exact` |
|---|---|---|---|
| what it pairs | templates that share enough words (Jaccard similarity of the word sets, at least 0.6) | templates of equal length where one generalizes the other (`<*>` against a word) | nothing: a template is the same only if its text is the same |
| speed | the same as the others on real logs; +0.07 s on a worst-case `diff` of 18 thousand one-sided templates | +0.03 s on the same | the fastest, by those fractions of a second |
| accuracy | the best: 16-71 percent fewer false alarms on saved results; finds 89 percent of the reworded messages in the tests | 2-62 percent fewer false alarms on saved results; finds no reworded message | no pairing, every reword is a new and a disappeared template |
| risk | may join two similar templates that are different messages (1 pair of 206 in the tests) | only safe merges (one template generalizes the other) | none |

Three more matchers ship as default plugins, all computed by the Rust core. `jaccard-idf` and `overlap` are experimental
options: on the measurements in [`bench/docs/DIFF_MATCHERS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/DIFF_MATCHERS.md#the-040-matchers-accuracy)
neither is better than `jaccard`, which stays the default. What each one is for, and what it is not:

**`jaccard-idf`**: Jaccard similarity where a word weighs `1 / (the number of one-sided templates that contain it)`, at least
0.5. Shared rare words count, shared common words hardly.

- Use it when you would rather miss a pairing than make a wrong one: it pairs about half as many unrelated templates as
  `jaccard` and made no false merge in the tests (`novel` mode: 0 of 29 pairs on the BGL log, 0 of 248 on the four logs).
- It finds the reworded twins about as well as `jaccard` (BGL, saved results: 52 against 54 of 60 in `swap`, 49 against 49 of 59
  in `extend`).
- Do not use it to separate near-identical siblings, which is what it was designed for: it did not (5 of 60 mixed up, where
  `jaccard` has 5 and 6). Do not use it to get the fewest alarms on saved results: it leaves more of them than `jaccard`
  (BGL stationary pair 75 against 60, Thunderbird 310 against 138).
- Risk: one shared rare word (a host name, an id) outweighs many different common words.

**`overlap`**: shared words over the words of the shorter template, at least 0.8; a template of fewer than three words is never
paired. The overlap coefficient is built for a set that is contained in a bigger one, where Jaccard falls.

- Use it to explore, not to decide: when a message is known to have grown or shrunk (the new version adds context to it), run
  `diff` with it and read the pairs it makes.
- It did not find more twins than `jaccard` in the tests (BGL, saved: 53 against 54 of 60 in `swap`, 49 against 49 in `extend`),
  and it mixed up more siblings (7 and 8, against 5 and 6).
- Do not use it for a gate or for a result nobody reviews: a short template is "contained" in a long one that merely shares its
  words, and it joined different messages (`novel` mode: 1 of 57 pairs on the BGL log, 4 of 283 on the four logs). It hides the
  difference in size, by definition.

**`rules:FILE`**: the pairs you list, one `TEMPLATE <=> TEMPLATE` per line, see [the plugins guide](plugins.md#your-own-pairs-the-rules-matcher).

- Use it when you know the rewording (a release renamed a message and you have the list) and when a gate must not hide anything
  else: it pairs only what you declared, so a wrong pairing is a wrong rule, not a wrong score.
- It does not depend on how similar the texts are, so it also pairs messages that share no words.
- Limits: you maintain the file. A rule is matched against the mined template text (masked values, `<*>` where the miner
  generalized), so a rule written from an example line may not match; copy the template from a report. A rule that nothing
  matches is silent. It finds no rewording you did not list.

For every matcher, a paired template is reported as `changed`, not as `new`, so `--fail-on-new` and `--fail-on-new-alerts` do not
fire for it: the more a matcher pairs, the more real changes a gate can miss. `exact` and `rules:FILE` are the safe choices for
a gate.

In a `diff` of two logs (the shared tree and the recount) `token_subset` and `exact` give the same result, because the recount
already merges generalizations; `jaccard` differs only where templates keep host names or other literals. For saved results the
three differ most. The exit-code gates (`--fail-on-new`, `--fail-on-new-alerts`) count new templates only, and a paired template is
`changed`, so use `--matcher exact` for a gate that must fail on every new text. Measurements on four large real logs, and how they were made, are in
[`bench/docs/DIFF_MATCHERS.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/DIFF_MATCHERS.md).

## Check a log against a model

A saved model is what a good run looked like: its templates and their counts, never an example line. `check` compares a new log with it and
fails when the log holds anything the model does not know, without reading the good log again:

```
logfold learn good.log --state model.json
logfold check today.log --state model.json
```

```python
import logfold

logfold.analyze("good.log", save_state="model.json")
checked = logfold.check("model.json", "today.log")
if not checked.passed:
    for finding in checked.findings:
        print(finding.kind, finding.message)
```

The check fails (exit code 2, after the report is written) for each of these findings, and the output says which: more than 1% of the records fit no
template of the model (`--max-unmatched`), a new template of level WARN or higher (`--fail-on new-alerts`, or `new` for any new template), or no record
was read at all. The templates that the log has and the model does not are the new ones, with their counts, times and an example; the templates of
the model whose share moved a lot are listed as changed. `logfold match model.json today.log` only counts the records that fit no template, and
`logfold analyze today.log --load-state model.json --save-state model.json` continues a model with a new log. Use the same masks and parameters when
you learn and when you check; otherwise the command stops and says so. See [`check`](cli.md#logfold-check) and [`match`](cli.md#logfold-match).

## Mine a stream

A program that produces records while it runs (a service, a test harness, `tail -F`, `kubectl logs -f`) does not need a
file. `logfold stream` reads standard input and prints every template once, when it first appears:

```
kubectl logs -f deploy/api | logfold stream --format plain --save-state model.json --save-every 60
```

In Python, `logfold.Miner` keeps its templates between calls and takes records in batches:

```python
miner = logfold.Miner(format="app")
for batch in batches_of_lines():
    miner.add_many(batch)
    for template in miner.new_templates():
        print("new:", template)
result = miner.result()  # the same result as analyze() over the same records
# analyze(load_state=...), match() and Miner(load_state=...) read it
miner.save_state("model.json")
```

Mining is single-threaded per miner (about a million lines per second), so for several sources give each its own miner; they
run in parallel, and a miner shared by threads only takes turns:

```python
miners = {name: logfold.Miner(format="app") for name in ("api", "worker", "billing")}
# one thread (or task) per source:
miners["api"].add_many(batch_from_api)
```

To ask whether records fit the templates a miner holds, without learning them, use `miner.match_many(records)` (one native call
per batch) or `miner.match(record)`: each answer is a `TemplateMatch(id, text)` or `None`.

The result equals the one of `analyze` over the same records, whatever the size of the batches. `add_many` is the fast path
(a batch is one native call); `add_log_message` is one call per record and about 2.6 times slower. A stream cannot detect its
format, so it is `plain` unless you name one (`logfold inspect FILE` finds the format of a sample). Speed and memory:
[`bench/docs/STREAM.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/STREAM.md); the options are in
[the CLI reference](cli.md#logfold-stream) and [the API reference](api.md#miner).

## Find the values of a message

A template says that a part is variable; to see what it was in one message, pass the template (copy it from a report) and the
message to `logfold params` or to `logfold.extract_parameters`:

```python
template = "user <NUM> logged in from <IP>"
message = "user 42 logged in from 10.0.0.1:8080"
logfold.extract_parameters(template, message)
# (Parameter(position=1, name='num', value='42'),
#  Parameter(position=5, name='ip', value='10.0.0.1:8080'))
```

The names are those of the masking rules (`num`, `ip`, `ts`, ...) or `*` for a position the miner generalized, and the value is
the text as it was written, not the masked token. A message that does not fit the template (another number of tokens, or a
constant token that differs) gives `None`. Use the masks the template was mined with. See
[the API reference](api.md#extract_parameters) and [the CLI reference](cli.md#logfold-params).

## Reports

`--out FILE` writes a report; the suffix selects the format: `.html`, `.json`, `.txt` (plain text), `.md` (Markdown tables)
`.csv`, `.xml` (JUnit) or `.prom` (Prometheus). `--report NAME` picks the reporter by name instead (also `github-summary`
and `chat-message`, which have no suffix, and plugins): with `--out` it writes the
file, without it the text is printed instead of the tables. HTML reports are one self-contained file with a strict
Content-Security-Policy. JSON files follow the schemas in `docs/schema`.

## Formats

`logfold formats` lists them. `--format auto` (the default) samples the file and picks one; it fails with the best
guesses instead of guessing wrong silently.

| Name | Input |
|---|---|
| `plain` | the whole line is the message |
| `jsonl` | one JSON object per line; keys `message`/`msg`/`log`, `timestamp`/`time`/`ts`/`@timestamp`/`timeMillis`, `level`/`severity`/`lvl`/`log.level` |
| `journald` | `journalctl -o json` |
| `nginx`, `apache` | combined access log; the message is `"METHOD path HTTP/x" status` |
| `nginx-error` | nginx error log |
| `syslog` | classic (`Dec 13 11:35:28 host app[1]: ...`) and ISO-time (`2018-08-14T14:30:02+02:00 host app[1]: ...`, rsyslog's default on newer systems) syslog lines; lines that follow a record join it |
| `k8s` | CRI/containerd container logs (`kubectl logs` raw files) |
| `app` | `<ISO timestamp> [thread] LEVEL message`, typical of Python, Java and Go services |
| `logfmt` | `key=value` pairs (default plugin); starts with `ts=` or `time=`, then `level=` or `lvl=` (other plain pairs may stand between them); the rest is the message |
| `serilog-clef` | Serilog compact JSON (default plugin); `@m`/`@mt`, `@t`, `@l` |
| `haproxy` | HAProxy HTTP and TCP logs, with or without the syslog prefix (default plugin) |
| `postgresql`, `postgresql-csv` | PostgreSQL server log, `stderr` and `csvlog` (default plugins) |
| `docker-json` | Docker `json-file` driver lines: `log`, `stream`, `time` (default plugin; picked by `auto`) |
| `github-actions` | GitHub Actions job logs; `##[error]`, `##[warning]`, `##[debug]` are levels (default plugin) |
| `log4j` | log4j and logback output in the pattern `%d{ISO8601} %-5p [%t] %c - %m%n` (default plugin) |
| `log4j:<pattern>` | log4j or logback output in your own conversion pattern, for example `log4j:%d{HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n` |
| `regex:<pattern>` | your own pattern; named groups `message`/`msg`, `timestamp`/`time`/`ts`, `level`/`lvl` are used |

### What each format was checked on

The full account, with the numbers and what each check found, is [bench/docs/FORMAT_VALIDATION.md](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/FORMAT_VALIDATION.md); `logfold plugins info NAME` prints the same two columns. A check compares a format with a real program, with logs of other projects or with damaged logs; it does not promise that the format reads every log of that program.

<!-- format-checks:start -->
| Format | Checked on | Not checked |
|---|---|---|
| `apache` | Test logs of Filebeat's apache module, 4 of 5 (combined and vhost_combined). Picked by -f auto (as nginx, the pattern is the same). Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | A real Apache process; a custom LogFormat such as ssl_request_log (the time is not first: use regex:PATTERN). |
| `app` | Generated logs and the Hadoop set of Loghub (picked by -f auto, 2 of 2). Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | A program that writes exactly this shape: for Java logging use log4j:PATTERN, which was checked. |
| `docker-json` | Real Docker 28.3, json-file with and without a terminal, every line compared with what the container printed, including a line of 50,000 characters that Docker splits; Filebeat and Fluent Bit tests, 8 of 8. Picked by -f auto. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | Drivers other than json-file (local, journald, syslog); rotated files; entries with attrs or tag. |
| `github-actions` | The job logs of this project's own workflow runs, 39 of 39. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | Runs of other projects; GitHub Enterprise Server; self-hosted runners. Not picked by -f auto. |
| `haproxy` | Real HAProxy 2.8.30, 3.0.29 and 3.2.25 in Docker, the five forms of log stdout format, every record compared with the requests that were sent; Filebeat's HAProxy samples, 3 of 4. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | option httpslog; the CLF form (httplog clf is not supported); a log-format of your own; HAProxy 2.4 and older. Not picked by -f auto (read as syslog when it has the syslog prefix). |
| `journald` | Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | Real journalctl -o json output (Filebeat's samples are the export format, not JSON). |
| `jsonl` | Filebeat's samples of Elasticsearch, Logstash and MongoDB JSON logs, 8 of 14; inputs of Fluent Bit's Docker mode. Picked by -f auto. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | An object over several lines; a message that is not at the top level (log4j2's JsonLayout, Elasticsearch's slowlog); a time that is an object (MongoDB: records without time and level). |
| `k8s` | One Filebeat sample of the CRI format, 1 of 1. Picked by -f auto. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | A real containerd or CRI-O; more samples. |
| `log4j` | Real log4j2 2.25.2, logback 1.5.18 and log4j 1.x (reload4j 1.2.25) on Java 17 and 21, 23 patterns and zones, every record compared with the program's own record; two patterns of Kafka from Filebeat, 8 of 8. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | JsonTemplateLayout, %replace, %highlight, %d{UNIX}; rolling files; Android and Kotlin loggers. Not picked by -f auto (the pattern is a setting of the program). |
| `logfmt` | Loki's test logs, 2 of 2 (Go services, other pairs before level). Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | Real Go programs and logrus; not picked by -f auto. |
| `nginx` | Test logs of Filebeat's nginx module, 3 of 3 read as the project expects (a host in front, a chain of proxies); a generated 100 MB log for speed. Picked by -f auto. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | A real nginx process; a log_format other than the combined one. |
| `nginx-error` | Filebeat's nginx error test log, 1 of 1 (PHP warnings that continue an entry are joined). Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | More than one sample; a real nginx process. Not picked by -f auto on that sample. |
| `plain` | Nothing to compare with: every line is a record. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | Nothing format specific. |
| `postgresql` | Real PostgreSQL 13, 14, 15, 16 and 17 in Docker, 15 settings of the prefix, time zone and verbosity, every record compared with the server's own csvlog; Filebeat's samples of PostgreSQL 9.5 to 13, 12 of 12. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | jsonlog (PostgreSQL 15 and later); the syslog and eventlog destinations; a prefix that does not start with a time; other lc_messages languages. The zone name (CEST) is not applied. Not picked by -f auto. |
| `postgresql-csv` | Real PostgreSQL 13, 14, 15, 16 and 17 in Docker, every record compared with the server's stderr log; Filebeat's samples of PostgreSQL 11 and 13, 10 of 10. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | The syslog and eventlog destinations; other lc_messages languages. The zone name (CEST) is not applied. Not picked by -f auto. |
| `serilog-clef` | Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | Real Serilog output or samples of other projects; not picked by -f auto. |
| `syslog` | Filebeat's system syslog and auth logs, 7 of 7 (classic time, rsyslog's ISO time, macOS continuation lines); the Linux, Mac and OpenSSH sets of Loghub are picked as syslog by -f auto. Damaged logs (fuzzing: cut lines, CR LF, bytes that are not UTF-8, long lines); the chunking never changes the result. | A real syslog daemon; RFC 5424 lines. The classic time has no year (it reads as 1970). |
<!-- format-checks:end -->

Multi-line records (stack traces): `--multiline` joins lines that do not start a record to the previous one. With
`--format auto` indented continuation lines enable it automatically. A record takes lines only while it is smaller than
1 MiB (the rest of its lines are counted but not kept), and a line keeps its first 16 MiB.

## Parameters

| Option | Default | Meaning |
|---|---|---|
| `--depth` | 4 | tree depth (Drain3 convention, minimum 3) |
| `--sim-th` | 0.4 | similarity threshold: a line joins a template when at least this share of tokens matches exactly |
| `--max-children` | 100 | children per tree node |
| `--max-templates` | 100000 | cap on templates; what happens to further records is decided by `--on-full` |
| `--delimiters` | space, tab, CR, LF | the characters that separate tokens, replacing the default; `\t`, `\n`, `\r` and `\\` are escapes: `--delimiters ' \t\n\r_='` also splits `user_id=7` into `user`, `id` and `7` (keep the whitespace) |
| `--on-full` | `pool` | at the cap: `pool` puts new message shapes into catch-all templates; `evict` drops the least recently used templates and keeps learning (one tree, sequential); see below |
| `--no-masks` | off | do not mask values |
| `--high-cardinality` | off | mode for data with a huge number of distinct messages (see below) |
| `--strategy` | auto | `sequential` (one tree), `chunked` (parallel), `auto` (chunked above 64 MiB, sequential when almost every record is a new template) |
| `--threads`, `--chunk-mb` | all cores, 64 | parallel execution |
| `--examples` | raw | `masked` or `none` before sharing a report |

The parallel strategy cuts the file into fixed-size chunks, builds one tree per chunk and merges the trees in order. For
a fixed chunk size the result does not depend on the number of threads. With `auto`, the first chunk is watched: when
after its first 10 000 records it holds more than 0.3 templates per record (logs of unique messages), merging the chunk trees
would cost more than it saves, and the whole input is mined with one tree instead. `metrics.strategy` shows what was used.

A chunk tree begins empty, so the first records of every chunk are generalized before the common templates exist, and the stray
templates that result cannot be merged back: the parallel result holds more rare templates than the sequential one (HDFS without
masks: 341 against 43; the large templates are the same). `--warm-start` (`warm_start=True`) trains the first chunk alone and
starts every other chunk from a copy of its tree, which removes most of the strays. The price is a serial prefix of one chunk (a
smaller `--chunk-mb` makes it cheaper) and a copy of the tree per chunk; it does not apply to the sequential strategy, and
it is off by default. Numbers: [`bench/docs/WARM_START.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/WARM_START.md).

### A miner that runs for days

With the default policy a miner stops learning at `--max-templates`: the records of every new message shape go into one catch-all
template per length, even when old templates have not been seen for a long time. `--on-full evict` (`on_full="evict"`, `on_full =
"evict"` in `logfold.toml`) drops the least recently used templates instead, a tenth of the cap at a time, so that a stream keeps
learning. The counts of a dropped template join the catch-all template of its length, so the counts still add up to the number of
records; `run.evicted` and a warning say how many templates were dropped. Use it with `Miner` or `logfold stream`, which run for
long. It mines with one tree (a chunked strategy is refused), and a state must be used with the policy it was mined with; a miner
continued from a state continues exactly (the state keeps the order in which the templates were last used). Cost: when every record opens a
new template, mining is about 3.5 times slower than pooling (148 thousand against 523 thousand lines per second at a cap of 5000,
`bench/docs/STREAM.md`); with few new templates there is no difference.

### High-cardinality data

Free-form text, random ids or hashes in every line can produce one template per line. Mining that is slow and
memory-hungry for any Drain-based tool. `--high-cardinality` (`high_cardinality=True` in Python) caps the templates at
5000 (unless you pass `--max-templates`), pools every further record into catch-all templates (`<*> <*> ...`, one per
token count; counts stay exact) and runs sequentially, because merging huge trees costs more than parallelism saves.
On a 10 MB file with about 84 000 distinct lines this turns 2.0 s into 0.14 s. A warning tells you when the cap was hit,
also without the mode. With `--strategy auto` such a log is noticed after the first chunk and mined sequentially even
without the mode, but the mode is faster and keeps the result short.

## Extending logfold

Plugins are ordinary Python packages that declare entry points.

The [plugins guide](plugins.md) explains how to use and write each kind (formats, reporters, diff matchers); a complete
installable example is in [`examples/logfold-example-plugin`](../examples/logfold-example-plugin).

```toml
[project.entry-points."logfold.formats"]
myapp = "my_plugin:MYAPP"

[project.entry-points."logfold.reporters"]
markdown = "my_plugin:MarkdownReporter"

[project.entry-points."logfold.matchers"]
first_word = "my_plugin:FirstWordMatcher"
```

```python
from logfold.ext import RegexFormat

MYAPP = RegexFormat(
    name="myapp",
    pattern=r"^(?P<ts>\d{2}/\w{3}/\d{4}:[\d:.]+) (?P<lvl>\w+) (?P<msg>.*)$",
    message_group="msg",
    time_group="ts",
    level_group="lvl",
    ts_format="%d/%b/%Y:%H:%M:%S.%f",
)
```

A format plugin returns **data** (a `RegexFormat`, `JsonFormat` or `PlainFormat`), not code: the engine compiles it into
a fast parser, so plugins cost nothing per line. `Reporter` and `DiffMatcher` are protocols in `logfold.ext`.

## Engines

The Rust engine does the mining (`engine="auto"` and `engine="native"` are the same); its behavior is the contract in
`docs/ALGORITHM.md`. If the extension is missing or speaks another contract version, mining raises an `EngineError`
that asks for a reinstall. The value `engine="python"` of the removed pure-Python engine still works: it runs the Rust
engine with a deprecation warning, and will be refused in a later release. State files (`save_state`, `load_state`, see
[the CLI reference](cli.md#state-files)) are read and written by the Rust engine.

## Security

Log lines are untrusted: HTML reports escape everything and carry a strict Content-Security-Policy. Example messages
are raw lines; use `--examples masked` or `none` before sharing a report. See `SECURITY.md`.

To keep secrets and personal data out of templates, saved states and examples, choose the mask sets: `--masks all`
(library `masks=["all"]`) hides private keys, tokens, API keys, passwords, e-mail addresses, phone numbers, card numbers and
IBANs, and your own sets (`--masks-file`, a plugin) hide your own identifiers; add `--examples masked` so that the examples
use the same rules. The sets are split by cost: `secrets` and `pii` add about 5 to 15% to a run on 100 MB logs, `all` about 11
to 24% (`credentials` and `payment` read every byte). The sets lower the risk and do not remove it. See the
[mask sets](cli.md#mask-sets) and [writing one](plugins.md#mask-sets).
