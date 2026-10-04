# Benchmark results

Protocol: [`PROTOCOL.md`](PROTOCOL.md). Raw data: [`results/`](results).

Machine: Windows-11-10.0.26200-SP0, 8 physical / 16 logical cores, 34.2 GB RAM, Python 3.13.0.

Tools: logfold: logfold 0.1.0.dev0; logdrain: logdrain 0.3.2; logdelta: logdelta 0.3.4; drain3: drain3 0.9.11.

Wall time of the median of the repeats in seconds, with throughput in MB/s in brackets. Best per column in bold.

## Analyze, no masking

| tool | nginx s (MB/s) | app s (MB/s) | loghub s (MB/s) | highcard s (MB/s) | highcard@10MB s (MB/s) | peak MB (max over all runs) |
|---|---:|---:|---:|---:|---:|---:|
| Drain3 (Python) | 5.26 (20) | 9.03 (12) | 21.95 (5) | - | - | 41 |
| logfold 1 thread | 0.62 (170) | 0.71 (149) | 1.39 (75) | 4.44 (24) | 2.33 (4) | 283 |
| logfold 16 threads | **0.37 (285)** | **0.37 (281)** | **0.82 (128)** | 8.72 (12) | 2.84 (4) | 1,885 |
| logdrain (Rust) | 5.27 (20) | 5.02 (21) | 2.24 (47) | 3.31 (32) | 0.56 (19) | 1,289 |
| logfold high-cardinality mode | - | - | - | **1.44 (73)** | **0.53 (20)** | 54 |

## Analyze, with masking

| tool | nginx s (MB/s) | app s (MB/s) | loghub s (MB/s) | highcard s (MB/s) | highcard@10MB s (MB/s) | peak MB (max over all runs) |
|---|---:|---:|---:|---:|---:|---:|
| Drain3 (Python) | 26.82 (4) | 24.62 (4) | 35.37 (3) | - | - | 41 |
| logfold 1 thread | 1.13 (93) | 0.96 (109) | 1.83 (57) | 5.93 (18) | 2.54 (4) | 283 |
| logfold 16 threads | **0.46 (227)** | **0.42 (247)** | **0.85 (124)** | 8.46 (12) | 2.92 (4) | 1,885 |
| logdrain (Rust) | 1.49 (70) | 5.57 (19) | 2.91 (36) | 3.78 (28) | **0.58 (18)** | 1,289 |
| logdelta (Rust) | 7.34 (14) | 4.93 (21) | 6.99 (15) | 415.32 (0) | 4.83 (2) | 634 |
| logfold high-cardinality mode | - | - | - | **3.03 (35)** | 0.68 (15) | 54 |

## Diff of two 100 MB runs (throughput counts both files)

| tool | nginx s (MB/s) | app s (MB/s) | peak MB (max over all runs) |
|---|---:|---:|---:|
| logfold diff 1 thread | 3.38 (62) | 2.90 (72) | 283 |
| logfold diff 16 threads | 0.80 (263) | 0.71 (294) | 1,885 |
| logfold diff 16 threads, --no-recount | **0.57 (368)** | **0.50 (419)** | 1,885 |
| logdelta diff (Rust) | 14.84 (14) | 11.60 (18) | 634 |


## Reading the numbers

**Speed-up over Drain3** (median wall time of Drain3 divided by logfold's):

| scenario | nginx | app | loghub |
|---|---:|---:|---:|
| no masking, 1 thread | 8.5× | 12.8× | 15.8× |
| no masking, 16 threads | 14× | 24× | 27× |
| masking, 1 thread | 24× | 25× | 19× |
| masking, 16 threads | 58× | 58× | 42× |

The specification's hypothesis was 20–50×. It holds for masked analysis and for the parallel mode; without masking and in
one thread the gain is 8–16×, because Drain3 itself is cheap when it does no regex work.
`app_100mb` has 1.27 M lines: 0.37 s with 16 threads is about 3.4 M lines/s (target: 1 M lines/s on 8 cores).

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

**Diff.** `logdelta diff` took 11.6–14.8 s per pair against 0.7–0.8 s for logfold with the recount pass. The outputs are
not the same (logdelta groups findings into blocks, uses a G-test and several baselines; logfold reports shares and ratios),
so this is a speed comparison of two different reports.

**Memory.** Peak working set of the process tree, maximum over all runs of a tool. logfold: 42 MB with one thread and
93–107 MB with 16 threads on the regular datasets; on `highcard` (10⁵ templates) 283 MB sequentially and 1.9 GB with 16
threads, where every chunk builds its own huge tree (the high-cardinality mode needs 54 MB). Drain3 41 MB, logdelta
9–154 MB, logdrain over 1.2 GB. For logfold, memory depends on the number of templates, not on the file size.

## High-cardinality data

`highcard` is adversarial: 6–15 random words per line, about 10⁵ distinct templates. It is the weak case for the default
configuration: 4.4 s per 100 MB with one thread and 8.7 s with 16 (**chunked is slower than sequential**: merging chunk
trees of 10⁵ templates costs more than parallelism saves), and the result is an unreadable list of one-line templates.

`--high-cardinality` (templates capped at 5000, the rest pooled into catch-all templates, sequential) addresses it:

| | 10 MB | 100 MB |
|---|---:|---:|
| logfold, default, 1 thread | 2.33 s | 4.44 s |
| logfold, default, 16 threads | 2.84 s | 8.72 s |
| logfold, high-cardinality mode | **0.53 s** | **1.44 s** |
| logdrain (does different work, see above; its leaf cap bounds the work per line) | 0.56 s | 3.31 s (3.78 s with masks) |
| logdelta (masks) | 4.83 s | **415 s** |
| Drain3 | 461 s (one run) | not measured (hours; see below) |

logdelta's time grows much faster than the data (4.83 s for 10 MB, 415 s for 100 MB). Drain3 already needed 461 s for
10 MB, so it was not attempted on 100 MB. At this size logfold's mode is 2.3× faster than logdrain and 290× faster than logdelta.

The time of the 10 MB run is dominated by interpreter start-up and imports (about 0.4 s); inside the library the same file
takes 0.14 s. With masking the mode needs 0.68 s and 3.03 s. The price of the mode: templates beyond the first 5000 are not
kept apart (counts stay exact, and a warning says so).

## Limitations

- One machine (Windows 11, i7-10700K, 8 cores / 16 threads), warm page cache, generated data (nginx, app, Loghub-2k
  derived loghub, highcard); Loghub-2.0 could not be downloaded.
- Rows come from several runs on the same machine (marked per row by `measured_in` in the files in `results/`);
  repeated measurements agreed within about 5%.
- Absolute numbers will differ on Linux and with a cold cache.

