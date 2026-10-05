## Reading the numbers

**Speed-up over Drain3** (median wall time of Drain3 divided by logfold's):

| scenario | nginx | app | loghub |
|---|---:|---:|---:|
| no masking, 1 thread | 7.7× | 12.4× | 18.8× |
| no masking, 16 threads | 13.7× | 22.0× | 39.2× |
| masking, 1 thread | 26.3× | 26.3× | 25.5× |
| masking, 16 threads | 59.9× | 58.3× | 60.9× |

The specification's hypothesis was 20–50×. It holds for masked analysis and for the parallel mode; without masking and in
one thread the gain is 8–19×, because Drain3 itself is cheap when it does no regex work.
`app_100mb` has 1.27 M lines: 0.41 s with 16 threads is about 3.1 M lines/s (target: 1 M lines/s on 8 cores).

**Equivalence of work** (`results/templates.json`, template counts):

| dataset | logfold | Drain3 | logdrain | logdelta |
|---|---:|---:|---:|---:|
| nginx, masked | 2 | 2 | 2 (`--masks uuid,hex32,ipv4`) | 2 |
| app, masked | 12 | 12 | 599 841 | 12 |
| loghub, masked | 1 364 | 1 363 | 160 437 | 1 380 |
| nginx, no masks | 2 | 2 | 593 308 | n/a |
| app, no masks | 12 | 12 | 599 841 | n/a |
| loghub, no masks | 1 593 | 1 592 | 160 433 | n/a |

logfold reproduces Drain3's templates (also on all 16 Loghub-2k sets, `eval/results/quality.json`). logdelta finds the
same number of templates as logfold on all three datasets (it cannot run without masks), so its timings compare equal
work.

**logdrain does different work** (from its source, version 0.3.2):

- Numeric parametrization (on by default) wildcards only tokens made of digits only (`is_numeric_token`), while Drain3
  treats any token containing a digit as variable. IPs, timestamps and ids therefore stay literal and open new tree
  branches: hundreds of thousands of clusters and more than 1 GB of memory.
- Every tree leaf keeps at most 100 clusters (`max_clusters_per_leaf`) and evicts the oldest (LRU). This bounds the work
  per line, but templates can be lost; logfold keeps every template until `max_templates` is reached.
- It is an online miner with per-template time statistics and a thread-safe sharded tree; it returns a cluster id per
  line, does not compare two runs, and has no masks by default.
- The CLI exposes none of these options, nor custom masks. The leaf cap is the likely reason for its speed on
  high-cardinality data (not tested by changing it).

Its timings are therefore not a like-for-like comparison, and the library's own figure (1–2 M lines/s per core) was not
reproduced through its CLI.

The `loghub` dataset was regenerated once: the first version randomised every digit, which produced a different date on
every line (`77/82/51`) and made logdelta create 81 145 templates. Real logs change dates slowly, so the generator now
keeps short numbers (dates, times) and randomises only long ones (ids, ports, addresses).

**Diff.** `logdelta diff` took 11.6–14.8 s per pair against 0.7 s for logfold with the recount pass. The outputs are
not the same (logdelta groups findings into blocks, uses a G-test and several baselines; logfold reports shares and ratios),
so this is a speed comparison of two different reports.

**Memory.** Peak working set of the process tree, maximum over all runs of a tool. logfold: 42–66 MB with one thread and
93–130 MB with 16 threads on the regular datasets; on `highcard` (10⁵ templates) 284 MB sequentially and 1.9 GB with 16
threads when the strategy is forced to `chunked`, because every chunk builds its own huge tree (the default `auto` strategy notices this after the first chunk and mines sequentially: 553 MB with 8 MiB chunks, 286 MB with the default chunk, see `ADAPTIVE.md`; the high-cardinality mode needs 54–55 MB). Drain3 41 MB, logdelta
9–154 MB, logdrain over 1.2 GB. For logfold, memory depends on the number of templates, not on the file size.

## High-cardinality data

`highcard` is adversarial: 6–15 random words per line, about 10⁵ distinct templates. It is the weak case for the default
configuration: 4.3 s per 100 MB with one thread and 8.1 s with 16 when the strategy is forced to `chunked` (**chunked is
slower than sequential**: merging chunk trees of 10⁵ templates costs more than parallelism saves). The default `auto`
strategy now sees this in the first chunk and mines sequentially, see `ADAPTIVE.md`. The result is still an unreadable list
of one-line templates.

`--high-cardinality` (templates capped at 5000, the rest pooled into catch-all templates, sequential) addresses it:

| | 10 MB | 100 MB |
|---|---:|---:|
| logfold, default, 1 thread | 2.39 s | 4.29 s |
| logfold, default, 16 threads | 2.86 s | 8.06 s |
| logfold, high-cardinality mode | **0.51 s** | **1.51 s** |
| logdrain (does different work, see above; its leaf cap bounds the work per line) | 0.56 s | 3.31 s (3.78 s with masks) |
| logdelta (masks) | 4.83 s | **415 s** |
| Drain3 | 461 s (one run) | not measured (hours; see below) |

logdelta's time grows much faster than the data (4.83 s for 10 MB, 415 s for 100 MB). Drain3 already needed 461 s for
10 MB, so it was not attempted on 100 MB. At this size logfold's mode is 2.2× faster than logdrain and 275× faster than logdelta.

The time of the 10 MB run is dominated by interpreter start-up and imports (about 0.4 s); inside the library the same file
takes 0.14 s. With masking the mode needs 0.57 s and 1.98 s. The price of the mode: templates beyond the first 5000 are not
kept apart (counts stay exact, and a warning says so).

## Limitations

- One machine (Windows 11, i7-10700K, 8 cores / 16 threads), warm page cache, generated data (nginx, app, Loghub-2k
  derived loghub, highcard). The large real Loghub-2.0 files are measured separately for logfold only, see
  [`LOGHUB2.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/LOGHUB2.md).
- Rows come from several runs on the same machine (marked per row by `measured_in` in the files in `results/`);
  repeated measurements agreed within about 5%. The logfold rows are from run 5 (logfold 0.2.0 plus the performance
  changes of `main` made after it, measured in a clean environment with no plugin packages installed); the Drain3,
  logdrain and logdelta rows are from earlier runs on the same machine.
- Absolute numbers will differ on Linux and with a cold cache.
