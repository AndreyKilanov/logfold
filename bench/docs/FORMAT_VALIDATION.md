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
