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
