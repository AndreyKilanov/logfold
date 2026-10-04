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

**logdrain does different work.** In its code, numeric parametrization (on by default) wildcards only tokens made of
digits only (`is_numeric_token`), while Drain3 treats any token containing a digit as variable. IPs, timestamps and ids
therefore stay literal and open new tree branches: hundreds of thousands of clusters and more than 1 GB of memory. The
CLI exposes neither that option nor custom masks. Its timings are not a like-for-like comparison, and the library's own
figure (1–2 M lines/s per core) was not reproduced through its CLI.

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
| logdrain (does different work, see above) | 0.56 s | not measured |
| logdelta | 4.83 s (masks) | not measured |
| Drain3 | 461 s (one run) | not measured |

The time of the 10 MB run is dominated by interpreter start-up and imports (about 0.4 s); inside the library the same file
takes 0.14 s. With masking the mode needs 0.68 s and 3.03 s. The price of the mode: templates beyond the first 5000 are not
kept apart (counts stay exact, and a warning says so).

## Limitations

- One machine (Windows 11, i7-10700K, 8 cores / 16 threads), warm page cache, generated data (nginx, app, Loghub-2k
  derived loghub, highcard); Loghub-2.0 could not be downloaded.
- Rows come from several runs on the same machine (marked per row by `measured_in` in `results/results.json`);
  repeated measurements agreed within about 5%.
- Absolute numbers will differ on Linux and with a cold cache.
