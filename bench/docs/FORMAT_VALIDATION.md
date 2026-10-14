# Checking the built-in formats against real software

The tests of the formats read logs that we generated from our own idea of the format. If we misread a format, the
generator and the parser are wrong in the same way and the tests still pass. This page records the checks where **a real
program writes the log and the expected result comes from the program**, not from us. It grows with each format; the
final table of the task joins them.

Run: `python bench/validate/formats.py` (needs `docker` and the extension built with `maturin develop --release`; the
containers are named `logfold-validate-*` and removed at the end; the first run pulls the images).

## PostgreSQL (`postgresql`, `postgresql-csv`)

**The oracle.** PostgreSQL writes the same events to the `stderr` log and to `csvlog` at once (`logging_collector=on`,
`log_destination=stderr,csvlog`). The rows of the csvlog, read with Python's `csv` module, say how many entries there
are, how many lines and how many physical lines each one makes in the `stderr` log (the message and its `DETAIL`, `HINT`,
`QUERY`, `CONTEXT`, `LOCATION` and `STATEMENT` lines), the severity of each and the first and last time. The server is
stopped before the files are read, so both are complete.

**The events.** Numbered `RAISE LOG`, `INFO`, `NOTICE` and `WARNING`; `RAISE EXCEPTION` with a two-line `DETAIL` and a
`HINT` (which adds `CONTEXT` and `STATEMENT`); a syntax error (which adds ` at character 1` to the message); a
three-line statement logged by `log_min_duration_statement=0`; a refused connection (`FATAL`); a real deadlock between two
sessions; and the server's own start and stop messages. About 260 entries and 470 `stderr` lines per run.

**What is compared**, for `-f postgresql` on the `stderr` log and `-f postgresql-csv` on the csv file: the number of
records, the lines that were not parsed (must be 0), the records per level, the first and last time, and **every record**
as `(level, first line of the message, physical lines)` as a multiset (two sessions that log at the same moment reach the
two files in different orders). A control run with a wrong level, a split statement and a missing record confirmed that the
comparison finds them.

| setting | entries | `stderr` lines | `-f auto` | result |
|---|---:|---:|---|---|
| 13 `%m [%p] ` | 258 | 462 | refused | all numbers match |
| 13 `%m [%p] %q%u@%d ` | 258 | 462 | refused | all numbers match |
| 14 `%m [%p] ` | 258 | 462 | refused | all numbers match |
| 14 `%m [%p] %q%u@%d ` | 258 | 462 | refused | all numbers match |
| 15 `%m [%p] ` | 262 | 466 | refused | all numbers match |
| 15 `%m [%p] %q%u@%d ` | 262 | 466 | refused | all numbers match |
| 16 `%m [%p] ` | 262 | 466 | refused | all numbers match |
| 16 `%m [%p] %q%u@%d ` | 262 | 466 | refused | all numbers match |
| 17 `%m [%p] ` | 262 | 466 | refused | all numbers match |
| 17 `%m [%p] %q%u@%d ` | 262 | 466 | refused | all numbers match |
| 17 `%t ` (seconds only) | 262 | 466 | refused | all numbers match |
| 17 `%t [%p]: [%l-1] user=%u,db=%d,app=%a,client=%h ` | 262 | 466 | refused | all numbers match |
| 17 `%m [%p] `, `log_error_verbosity=verbose` | 262 | 728 | refused | all numbers match |
| 17 `%m [%p] `, `log_timezone=America/New_York` | 262 | 466 | refused | all numbers match |
| 17 the `%t` prefix above, `log_timezone=Asia/Kolkata` | 262 | 466 | refused | all numbers match |

Images: `postgres:13.23`, `14.24`, `15.19`, `16.15`, `17.11` (Debian). Measured 2026-10-15.

**What this found.** No difference in the parsing of either format. The differences that the first runs showed were all in
the oracle itself and were corrected there: the line feeds of the script that `psql` read (Windows turned them into CR LF
and so changed the logged statements), the ` at character N` that the server adds to a message with a position, the
SQLSTATE in front of the message under `verbose`, the order of entries of two concurrent sessions, and the second-only
precision of `%t`.

**Behaviors that the check confirmed or showed, not defects:**

- `-f auto` does not recognize either PostgreSQL format: it refuses with the list of best guesses (the format has to be
  named, as the documentation says). The detection matrix is a later step of the task.
- `LOG`, `DEBUGn` and the `DETAIL`, `HINT`, `CONTEXT`, `STATEMENT`, `QUERY` and `LOCATION` lines have no level, as
  documented; the server's `NOTICE` and `INFO` read as `INFO`, `WARNING` as `WARN`, `PANIC` as `FATAL`.
- Under `log_error_verbosity=verbose` the SQLSTATE and a colon (`00000: `) stay at the start of the message, so they are
  part of the template.

**Not checked:** `jsonlog` (PostgreSQL 15 and later; not a built-in format), the `syslog` and `eventlog` destinations,
`log_line_prefix` values that do not start with a timestamp, other `lc_messages` languages, autovacuum and checkpoint
messages, logs over 100 MB (the check runs on about 40 KB).

## HAProxy (`haproxy`)

**The oracle.** HAProxy 2.8.30, 3.0.29 and 3.2.25 answer numbered requests themselves (`http-request return`, `deny`, a
backend whose only server is down) and log to their standard output in each form of `log stdout format`. The requests
come from a second container that shares the network of the first, so no other connection (Docker Desktop's probes of a
published port showed up as `GET /` and `<BADREQ>` lines) reaches the log. What was sent is the expected result: per
round `GET` and `POST` answered with 200, `GET` denied with 403, `HEAD` and `GET` to a backend that is down (503, one with
a 1,500-character query that HAProxy cuts in the log), two plain TCP connections to a `mode tcp` frontend, and one
garbage request (`<BADREQ>`, 400). 20 rounds: 160 lines per run, and four `Proxy ... stopped` lines of the shutdown.

**What is compared:** the records read by `-f haproxy` (160), the lines not parsed (exactly the shutdown lines, nothing
else), the accept times (inside the time of the run), and **every record** as `(frontend, backend, status, method, path)`
as a multiset, read back from the record with a pattern of the script and not of logfold.

| HAProxy | `raw` | `short` (`<6>`) | `iso` | `rfc3164` | `rfc5424` |
|---|---|---|---|---|---|
| 2.8.30 | match | match | match | match | match |
| 3.0.29 | match | match | match | match | match |
| 3.2.25 | match | match | match | match | match |

`option httplog clf` (3.2.25, `raw`): not supported, as documented; the 40 connection lines of `tcplog` are read, the 120
CLF request lines are not.

**What this found.** The `iso` (an ISO time in front of the line) and `rfc5424` (`<134>1 time host haproxy pid - - `) forms
were **not read at all**: 0 records of 160, although the documentation promised the syslog prefix. The pattern allowed
only the `rfc3164` prefix. Fixed in the format, with a test made of lines that HAProxy wrote (`tests/plugins/test_format_plugins.py`).

**Not checked:** `option httpslog`, `log-format` that you write yourself, syslog over UDP with a real host name, HAProxy 2.4
and older, logs of the `stats` socket and of the master process.

## Docker `json-file` (`docker-json`)

**The oracle.** A container prints numbered lines on stdout and stderr, empty lines, non-ASCII text, a tab, quotes, a
backslash, an escape sequence, a line of 50,000 characters (Docker splits it into entries of 16 KB) and a last line without
a line break. The real `*-json.log` file is read back (`LogPath` of the container) and parsed with Python's `json`
module: every line of the file is one entry. The printed lines are rebuilt from the entries and compared with what was
printed, which proves that the file holds what was written. The same run with a terminal (`-t`: lines end with CR LF and
stderr joins stdout).

**What is compared:** records (one per printed line), lines not parsed (0), the message of every record against the printed
line (as a multiset), and the first and last time (those of the first entry of a line; nanoseconds cut to microseconds).

| setting | entries | result |
|---|---:|---|
| `json-file` | 59 | all numbers match |
| `json-file` with a terminal (CR LF) | 59 | all numbers match |

**What this found.**

- The message of a record kept the line break of the entry (`line 1 stdout` plus a line feed): in the examples of a report
  and in `inspect`. The documentation said that it was dropped; the templates were right only because the line feed is a
  delimiter. Fixed: a JSON message loses one line break at its end (`\n` or `\r\n`), so a terminal's CR LF goes too
  (`docs/ALGORITHM.md`, a Rust test).
- **A limit that was fixed in the same change:** the entries of a line longer than 16 KB (Docker cuts it into pieces of
  16 KB, and only the last piece ends with a line break) were read as records of their own (7 in the first run).
  `docker logs` shows them as one line, and now so does logfold: `docker-json` joins an entry whose message has no line
  break at its end with the entries that follow it, up to the one that has. The record has the time of the first
  piece. The rule works on neighbours: a piece of stdout and an entry of stderr that Docker wrote between two of its
  pieces would be joined, as `docker logs` prints them. The result does not depend on the chunking of a big file (tested
  with chunks of 1 byte and more, in the engine and in the streaming `Miner`).

**Not checked:** other drivers (`local`, `journald`, `syslog`), a log that Docker rotates (`max-size`), compressed rotated
files, entries with `attrs` or `tag`.

## Java logging libraries (`log4j`, `log4j:<pattern>`)

**The oracle.** A Java program (`bench/validate/java/`, compiled and run in a Temurin 17 or 21 container with
libraries downloaded at pinned versions and SHA-256) writes numbered events through **log4j2 2.25.2**, **logback 1.5.18**
and **log4j 1.x (reload4j 1.2.25)** and keeps its own record of them: the level, the first line of the message, how many
lines the event added to the log file (counted from the growth of the file, so no parser decides where an event ends) and
the wall-clock time just before and just after the call. Per round (20 rounds, 300 to 320 events and 1,140 to 1,160 lines
per run): every level, an empty message, a message of several lines with a blank line inside, an exception with a cause
chain, a suppressed exception and `... N more`, the same under a multi-line message, a 20,000-character message, a message
full of regex characters with an exception whose message has two lines, an MDC value, and three thread names (one with
spaces).

**What is compared**, for `-f "log4j:<pattern>"` with the pattern that the program used: the number of records, the lines
that were not parsed (0), and **every record in order**: the level, the first line of the message, the number of
non-blank physical lines, and a time between the two clock readings (the time of day only when the pattern has no date;
wall-clock time in the zone of the JVM, `UTC`, `Asia/Kolkata` and `America/New_York`).

| library | pattern | result |
|---|---|---|
| log4j2 (Java 17, 21) | `%d{ISO8601} %-5p [%t] %c - %m%n` (the `log4j` default) | match |
| log4j2 | `%d{yyyy-MM-dd HH:mm:ss.SSS} [%t] %-5level %logger{36} - %msg%n` | match |
| log4j2 | `%d{ISO8601} %-5p [%t] %c{1.} (%X{requestId}) - %m%n` | match |
| log4j2 | `%d{DATE} [%t] %-5p %c{1} - %m%n` | match |
| log4j2 | `%d{HH:mm:ss.SSS} ...`, `%d{ABSOLUTE} ...` (time only) | match |
| log4j2 | `%d{DEFAULT} %p %c{1.} [%t] %m%n%ex` | match (refused before the fix) |
| log4j2 | `%d{DEFAULT} %p [%t] %m%ex%n` | match (see the note below) |
| log4j2 | Spring Boot file pattern, `%d{yyyy-MM-dd'T'HH:mm:ss.SSSXXX} %5p 1 --- [%15.15t] %-40.40logger{39} : %m%n%ex` | match (refused before the fix) |
| log4j2, zone `Asia/Kolkata` | the default pattern | match |
| logback (Java 17, 21) | `%d{ISO8601} %-5p [%t] %c - %m%n`, `%d [%t] %-5p %c - %m%n` | match |
| logback | `%d{yyyy-MM-dd HH:mm:ss.SSS} [%thread] %-5level %logger{36} - %msg%n`, and the same with `%d{HH:mm:ss.SSS}` | match |
| logback | `... [%X{requestId:-none}] ...`, Spring Boot pattern | match |
| logback, zone `America/New_York` | the default pattern | match |
| log4j 1.x | `%d{ISO8601} %-5p [%t] %c - %m%n`, `%d [%t] ...`, `%d{ISO8601} %-5p %c{1}:%L - %m%n`, `%d{dd MMM yyyy HH:mm:ss,SSS} ...` | match |

**What this found.**

- **`%d{DEFAULT}` was refused** ("the date letter 'D' ... is not supported"): `DEFAULT` is the name log4j2 uses when you
  write `%d` and the one its documentation shows. Fixed together with the other names of log4j2 (`DEFAULT_MICROS`,
  `DEFAULT_NANOS`, `ABSOLUTE_MICROS`, `ABSOLUTE_NANOS`, `COMPACT`, `ISO8601_OFFSET_DATE_TIME_HH`, `_HHMM`, `_HHCMM`).
  `UNIX` and `UNIX_MILLIS` (epoch numbers) are still refused, with the hint to write the format as `regex:<pattern>`.
- **A pattern with the exception after the newline was refused** ("a newline inside the pattern ..."): this is the
  file pattern of Spring Boot (`... : %m%n%wEx`) and the usual logback `%msg%n%ex`. The exception converters print on the
  lines after the record, so they may follow the `%n`; any other field after it is still refused.
- The first run of the oracle showed that logfold counts the lines of a record without its blank lines (the message with a
  blank line inside has one line less than the file grew). That is the documented meaning of `lines` ("non-blank"), so the
  oracle counts the same way; the blank line still belongs to the record and does not start a new one.

**Behaviors that the check confirmed or showed, not defects:**

- `-f auto` does not pick `log4j`: it refuses and lists the best guesses (the pattern is a setting of the program, so the
  format has to be named). The detection matrix is a later step of the task.
- log4j2 with `%m%ex%n` writes the first line of the exception **right after the message** on the same line
  (`evt 1 exceptionjava.lang.RuntimeException: outer 1`), so that is the message of the record. No parser can tell the
  two apart; `%m%n%ex` writes them on separate lines. The check expects the glued form for this pattern.

**Not checked:** other log4j2 layouts (`JsonTemplateLayout`, `%replace`, `%highlight`, `%style`), `%d{...}{timezone}` with a
zone other than that of the JVM, `%d{UNIX}`, logback `%nopex`, Android and Kotlin loggers, logs of other Java versions
than 17 and 21, rolling files, and a very long log (the check runs on about 120 KB).

## Logs that other people wrote (V2)

**The oracle.** Test logs of other open projects, each read with the format that is meant for it and compared with an
expectation that the project wrote (or, where there is none, with one that is computed from the file without `logfold`).
Nothing of theirs is in this repository: `bench/validate/external_samples.json` lists every file with its source,
commit and SHA-256, `external_samples.py` downloads it to `bench/data/formats/external/` (not tracked), and
`formats_external.py` compares. Sources and licences: `elastic/beats` (Filebeat module tests, Apache-2.0 outside
`x-pack`), `fluent/fluent-bit` (Apache-2.0), `grafana/loki` (AGPL-3.0: downloaded for the check only, never copied), and
the workflow runs of this repository (`gh api .../actions/runs/ID/logs`; the logs expire after 90 days, so these are the
newest runs on the day, not pinned).

Three oracles: **Filebeat's `*-expected.json`** (the boundaries of an event are the bytes from its `log.offset` to the next
one, the time is `@timestamp`, the level `log.level`; Filebeat keeps at most 100 events per file); **Docker's own rule**
for `json-file` (the entries of one printed line, read with Python's `json`); and **one event per line** with the time and
the level cut from the line by a regex (a line that does not start with a time joins the line before it, for GitHub Actions).

**What is compared:** the number of records and of lines that were not parsed, that every non-blank line is in a record or
in the unparsed count, and record by record, in order: the number of lines, the message (inside the text of the event),
the time (to the millisecond; a time that differs only by a zone offset is counted apart) and the level (only the levels
that `logfold` knows: `LOG`, `DETAIL` and so on have none).

| format | samples | match | sources |
|---|---:|---:|---|
| `apache` | 5 | 4 | Filebeat `apache/access` |
| `nginx` | 3 | 3 | Filebeat `nginx/access` |
| `nginx-error` | 1 | 1 | Filebeat `nginx/error` |
| `haproxy` | 4 | 3 | Filebeat `haproxy/log` |
| `postgresql` | 12 | 12 | Filebeat `postgresql/log`, PostgreSQL 9.5 to 13 |
| `postgresql-csv` | 10 | 10 | Filebeat `postgresql/log`, PostgreSQL 11 and 13 |
| `log4j:<pattern>` | 8 | 8 | Filebeat `kafka/log` (two patterns of Kafka) |
| `docker-json` | 8 | 8 | Filebeat and Fluent Bit tests (split lines, a broken line) |
| `k8s` | 1 | 1 | Filebeat CRI sample |
| `logfmt` | 2 | 2 | Loki test logs |
| `jsonl` | 14 | 8 | Filebeat Elasticsearch, Logstash and MongoDB JSON logs |
| `syslog` | 7 | 7 | Filebeat `system/syslog` and `system/auth` |
| `github-actions` | 39 | 39 | 3 runs of this repository, every job log |

Fewer than 20 samples for every format but `github-actions`: there are no more of them in these projects. Not covered by
other people's samples: `journald` (Filebeat's `.export` files are the export format, not `journalctl -o json`),
`serilog-clef`, `app`, `plain`.

**What this found, and what was fixed** (each fix has a test made of lines from the samples):

- **`nginx` and `apache` read only `client ident user [time]`.** Not read: a list of addresses in the first field
  (`10.0.0.2, 10.0.0.1, 127.0.0.1 - - [`, a proxy chain), a virtual host in front (`example.com 10.0.0.2 - - [`, Apache's
  `vhost_combined`), a quoted list. Now everything in front of the first `[date:` is the prefix. Same speed (0.41 s against
  0.40 s on 100 MB).
- **`nginx-error` did not join the lines of an entry** (PHP warnings of a FastCGI error continue on the next lines): they
  were counted as not parsed. Now it is multi-line.
- **`logfmt` needed `level=` right after `ts=`.** Lines of Go services (`ts=... caller=http.go:194 level=debug ...`, Loki,
  Prometheus) were not read (half of a Loki log), and so were logrus' `time="..." level=...` and `lvl=`. Now other plain
  pairs may stand between them. **Cost:** 0.62 s against 0.32 s on 500,000 lines (the regex no longer takes the fast path
  of the engine); both numbers are whole runs of `analyze` with the default strategy on 16 threads.
- **`jsonl` did not know `log.level` and `timeMillis`** (Elasticsearch's ECS logs, log4j2's JsonLayout): the level and the
  time were missing. Added to the default keys.
- **`syslog` read only the classic time** (`Dec 13 11:35:28`): the ISO time of rsyslog's default format on newer systems
  (`2018-08-14T14:30:02.203151+02:00 host prog[1]: ...`) was not read at all, and the lines that continue an entry (macOS)
  were not parsed. `ts_format` now falls back to ISO-8601 for a text it does not read (an engine change, in
  `docs/ALGORITHM.md` §1.3), and `syslog` takes both and joins continuation lines.
- **`github-actions` did not join the lines of a multi-line value** (the `with:` inputs of a step print their next lines
  without a time): 6 lines per job were not parsed. Now it is multi-line.

**Limits that were found and are written down, not fixed:**

- `apache`: a custom `LogFormat` (the `ssl_request_log` of Apache puts `[time]` first) is not the combined format; use
  `regex:<pattern>`. `haproxy`: the plain `Connect from ... to ...` messages of the default log mode are not HTTP or TCP logs.
- `jsonl`: one JSON object **per line**. A pretty-printed object over several lines (Elasticsearch's `stacktrace` arrays),
  a message that is not at the top level (log4j2's `logEvent.message`, Elasticsearch's `elasticsearch.slowlog.message`)
  and a time that is an object (MongoDB's `"t": {"$date": ...}`, with the level in `"s": "I"`) are not read; MongoDB's logs
  have records, but no time and no level.
- `postgresql`: the zone name of the time (`CEST`) is not applied, the time is the wall clock of the server. In 8 samples
  (130 times) the time differs from `@timestamp` only by that offset.
- `docker-json`: the `lines` of one inspected record that was joined from several entries is 1 (the counter of the run is
  right: it counts the physical lines).
- The classic syslog time has no year (1970).

## Damaged logs (V3)

**The oracle.** None from outside: the properties that must hold for any input. `tests/format_grammars.py` has a
Hypothesis grammar of valid lines for each of the 17 built-in formats, and a set of damages applied to the bytes of a whole
log: a line cut anywhere, a CR LF or CR line ending, a byte order mark, a banner and blank lines in front, a tab, a NUL, bytes that are not UTF-8,
a line of 5,000 or 70,000 bytes, an empty line, a shuffled order (time going backwards), a last line without a line break,
fields that are missing, several time zones and several `log4j` patterns.

**The properties** (`tests/api/test_format_fuzz.py`, `crates/logfold-tests/tests/engine_format_fuzz.rs`):

- no error and no hang (a deadline of 30 s per case);
- **conservation**: the lines of the sample are the non-blank lines of the file, and every one of them is in a record or in the
  count of lines not parsed;
- the sample reader (`inspect`) and the run (`analyze`) agree on the records and the lines not parsed;
- **the chunking changes nothing**: lines, records, lines not parsed and records per level are the same for the sequential
  run and for chunked runs of 1, 3, 17, 64 and 250 bytes on 1 to 4 threads (tiny chunks only for small logs); the Rust test
  does the same for six format kinds (plain, plain with a record start, regex, multi-line regex, JSON, joined JSON) on
  arbitrary bytes.

**Volume.** The CI profile is 40 cases for each of 36 checks (a minute). The last run on the final code was 300 cases
for each check (10,800 cases, 8 minutes) and 3,000 cases of the Rust test (6 kinds, 12 runs each, 7 minutes); all passed. An
earlier, heavier run (2,000 cases for each check, four processes) found the failures below on the earlier code and was
stopped for the heat of the processor when they were found; the 20,000 cases that the plan asked for were not run. Set
`LOGFOLD_FUZZ_EXAMPLES` and `PROPTEST_CASES` for a longer run.

**What this found, and what was fixed:**

- **A line with bytes that are not UTF-8 was not parsed by a regex or a JSON format.** A log in Latin-1 or Windows-1251, or a
  JSON string cut in the middle of a character, lost every line that has such a byte (`unparsed`), while `inspect` showed the
  line as read. `.` and `\S` of the regex engine cannot match such a byte, and the JSON reader refuses it. Now a line that
  does not match as it is, and is not valid UTF-8, is read once more with the bad bytes replaced by U+FFFD
  (`docs/ALGORITHM.md` §1.2); a line that is valid UTF-8 never pays for it.
- `RunSummary.lines` was described as the non-blank physical lines; it counts all physical lines, blank ones too. The
  description was corrected, the count did not change.

**Not covered:** memory of one huge record (the limit is tested by its own tests), a time window (`--since`/`--until`) with
chunks, `postgresql` multi-line statements of real length, and the Rust-side formats that are not built in.
