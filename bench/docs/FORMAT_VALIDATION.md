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
