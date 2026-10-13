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

## Several sources in parallel

One `Miner` mines in one thread (its tree is behind a lock), but every `Miner` has its own tree and lock, and the native
call releases the GIL, so one miner per source runs in parallel. `python bench/stream.py parallel FILE --workers N` feeds
lines that are already in memory (the first 600 thousand, or 1.2 million for 8 workers), in batches of 10000, from threads
of one process; median of 5. The lines are dealt to the workers in turn, so this measures throughput, not the templates of
real sources.

| Case | Wall | Lines per second | Against 1 miner |
|---|---:|---:|---:|
| 1 miner, 1 thread | 0.30 s | 1,990,839 | 1.00x |
| 4 miners, 4 threads (one per source) | 0.09 s | 6,677,484 | 3.35x |
| 1 shared miner, 4 threads | 0.26 s | 2,302,555 | 1.16x |
| 1 miner, 1 thread (1.2 million lines) | 0.62 s | 1,943,493 | 1.00x |
| 8 miners, 8 threads (one per source) | 0.22 s | 5,489,863 | 2.82x |
| 1 shared miner, 8 threads | 0.52 s | 2,301,931 | 1.18x |

A miner shared by several threads gains almost nothing (its calls are served one after another), so give every source its
own miner. A single very fast source cannot be spread over cores: the parallel mode of `analyze` (chunks, then a merge of
the trees) is not available for a stream, and it gives slightly more templates than one tree.

## Matching without learning

`Miner.match_many` assigns records to the templates a miner holds and changes nothing. `python bench/stream.py matching FILE` trains a
miner on the first 100 thousand lines of `app_100mb.log`, then times matching the first 600 thousand lines that are already in
memory (median of 5), and `add_many` over the same lines for comparison.

| Case | Wall | Lines per second | Against `match_many` of 10,000 |
|---|---:|---:|---:|
| `match_many`, batches of 100 | 0.39 s | 1,523,903 | 1.37x |
| `match_many`, batches of 1,000 | 0.25 s | 2,379,556 | 0.88x |
| `match_many`, batches of 10,000 | 0.29 s | 2,088,923 | 1.00x |
| `match_many` with `exact=True`, batches of 10,000 | 0.26 s | 2,328,605 | 0.90x |
| `match`, one record per call | 2.96 s | 202,719 | 10.30x |
| `add_many`, batches of 10,000 (mining the same lines) | 0.29 s | 2,035,122 | 1.03x |

Matching costs about what mining costs, and a batch of 1,000 or more is at full speed. One record per call is 10 times slower, as for
mining (the call and the Python wrapper around it cost more than the work), so `match_many` is the interface for more than a few
records.

**Many templates.** The data above has 12 templates. On `highcard_10mb.log` (83,745 lines of mostly unique messages) a miner
trained on the first 50,000 lines holds 50,000 templates, one per line. A record that fits one of them is found at once, but a
record that fits none used to be compared with every template of its token count: 2,000 unseen records took 1.96 s (1 ms each), and
matching all 83,745 lines took 31 s (2,700 lines per second) with the default rule and 11.7 s with `exact=True`, against 0.48 s
for mining the same lines. The scan was also what `logfold match` and the recount of `diff` did for such a record.

The templates of one token count now have an inverted index (token at a position to the templates that hold it), built when the
first such record asks for it and kept up to date after that. The similarity rule walks the lists of the positions that can
reach the threshold; the exact rule leaves out the lists of the three most common tokens of the message and tries separately the
templates that have three literal words or fewer. Both give the answer of the scan (`crates/logfold-tests/tests/core`: 24,000 probes
on growing trees, and the exact rule against a brute-force oracle). Result on the same data:

| Case | Before | Now |
|---|---:|---:|
| 2,000 unseen records, default rule | 1.96 s | 0.12 s |
| 2,000 unseen records, `exact=True` | 0.49 s | 0.002 s |
| all 83,745 lines, default rule | 31 s | 0.30 s |
| all 83,745 lines, `exact=True` | 11.7 s | 0.28 s |

Mining is not slower: `analyze` of the 100 MB file takes 0.77 s as before, and `add_many` of the 83,745 lines 0.48 s.

## Limits of this measurement

One machine and one dataset of 12 templates, so the cost of a large tree is not in it (`highcard` is the case for that, and
`Miner.result()` copies the templates, so its cost grows with their number). The stream is read from a file, not from a
pipe, so the time a writer takes to produce lines is not included.
