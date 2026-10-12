# Streaming interfaces: speed

`logfold.Miner` and `logfold stream` take records as they come instead of reading a whole file. This page measures what
that costs against `analyze`, and against Drain3, which has only the one-record-at-a-time interface.

## Method

`python bench/stream.py run FILE --variants ...` mines the same file in a separate process per variant, standard output
discarded, and records wall time, CPU time and peak memory the way `bench/speed.py` does (`measure`, median of 3, warm page
cache). Parameters are aligned: depth 4, similarity threshold 0.4, the default masks, plain text, no examples.

| Variant | What runs |
|---|---|
| `analyze` | `logfold analyze FILE -f plain --strategy sequential`: the reference, one tree, the same work |
| `stream` | `logfold stream FILE -f plain` (a reader thread, batches of 10000 lines) |
| `add_many` | `Miner.add_many` fed lists of 10000 lines read and stripped in Python |
| `add_lines` | `Miner.add_lines` fed lists of 10000 lines as read (with line feeds) |
| `add_log_message` | `Miner.add_log_message` once per line: one native call per record |
| `drain3` | Drain3 `add_log_message` once per line, the same six masks as regular expressions |

Data: `app_100mb.log` (105 MB, 1.27 million lines, 12 templates) and its first 10 MB. One machine (Windows 11, i7-10700K,
8 cores / 16 threads, Python 3.13), the 0.5.0 development code. The templates and counts of `analyze`, `Miner.add_many` and
`logfold stream` are identical on the whole 100 MB file (checked: 12 templates, 1,266,007 records).

## Results

100 MB:

| Variant | Wall | Speed | CPU | Peak memory | Against `analyze` |
|---|---:|---:|---:|---:|---:|
| `analyze` (sequential) | 0.78 s | 134 MB/s | 0.8 s | 44 MB | 1.00x |
| `add_lines` | 1.02 s | 103 MB/s | 1.0 s | 44 MB | 1.31x |
| `stream` | 1.11 s | 94 MB/s | 1.3 s | 79 MB | 1.42x |
| `add_many` | 1.22 s | 86 MB/s | 1.2 s | 44 MB | 1.56x |
| `add_log_message` | 3.12 s | 34 MB/s | 3.1 s | 40 MB | 3.98x |
| Drain3 `add_log_message` | 20.50 s | 5 MB/s | 20.4 s | 40 MB | 26x |

10 MB (the start of the interpreter and the imports take a large part of the time): `analyze` 0.34 s, `add_many` 0.34 s,
`add_lines` 0.32 s, `stream` 0.45 s, `add_log_message` 0.51 s, Drain3 2.26 s.

## Reading

- A batch interface costs 30-55% over `analyze` on the same file: the lines are read and cut in Python and cross the
  boundary as a list of strings. That is the price of taking records from a running program; `analyze` on a file stays the
  fastest way to mine a file.
- `add_lines` is the cheapest because the lines are not stripped in Python; `add_many` pays for `rstrip` of every line.
- One record per call (`add_log_message`) is 2.6 times slower than `add_many`, as the boundary rule predicts, and still 6.6
  times faster than Drain3 with the same loop. A batch of 10000 (`add_many`) is 17 times faster than Drain3.
- `logfold stream` was 2.3 times slower than `analyze` while its reader put one line at a time into the backlog (57 MB/s);
  reading in chunks and handing over a list of lines per chunk brought it to 94 MB/s. Its peak memory is the backlog limit
  (16 million characters) on top of the miner.
- The refactoring of the pipeline that made the session possible did not slow `analyze` down: sequential `analyze` on the
  100 MB file takes 0.77 s on `main` and 0.77-0.79 s on this branch (5 runs each, alternated).

## Limits of this measurement

One machine and one dataset of 12 templates, so the cost of a large tree is not in it (`highcard` is the case for that, and
`Miner.result()` copies the templates, so its cost grows with their number). The stream is read from a file, not from a
pipe, so the time a writer takes to produce lines is not included.
