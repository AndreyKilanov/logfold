# Benchmark results

Protocol: [`PROTOCOL.md`](PROTOCOL.md). Raw data: `bench/results/results.json`, `bench/results/results.json`, `bench/results/results.json`, `bench/results/results.json`, `bench/results/results.json`.

Machine: Windows-11-10.0.26200-SP0, 8 physical / 16 logical cores, 34.2 GB RAM, Python 3.13.0.

Tools: logfold: logfold 0.1.0.dev0; logdrain: logdrain 0.3.2; logdelta: logdelta 0.3.4; drain3: drain3 0.9.11.

Wall time of the median of the repeats in seconds, with throughput in MB/s in brackets. Best per column in bold.

## Analyze, no masking

| tool | nginx s (MB/s) | app s (MB/s) | loghub s (MB/s) | highcard s (MB/s) | highcard@10MB s (MB/s) | peak MB (max over all runs) |
|---|---:|---:|---:|---:|---:|---:|
| logfold 1 thread | 0.61 (171) | 0.70 (151) | 1.45 (72) | **4.35 (24)** | **2.31 (5)** | 42 |
| logfold 16 threads | **0.35 (300)** | **0.37 (284)** | **0.90 (116)** | 8.43 (12) | 2.70 (4) | 107 |
| Drain3 (Python) | 5.26 (20) | 9.03 (12) | 23.56 (4) | - | - | 31 |
| logdrain (Rust) | 4.93 (21) | 4.65 (23) | 2.72 (39) | - | - | 1,291 |

## Analyze, with masking

| tool | nginx s (MB/s) | app s (MB/s) | loghub s (MB/s) | peak MB (max over all runs) |
|---|---:|---:|---:|---:|
| logfold 1 thread | 1.10 (95) | 0.98 (107) | 1.94 (54) | 42 |
| logfold 16 threads | **0.43 (244)** | **0.41 (256)** | **1.00 (105)** | 107 |
| Drain3 (Python) | 26.82 (4) | 24.62 (4) | 35.93 (3) | 31 |
| logdrain (Rust) | 1.50 (70) | 5.53 (19) | 3.36 (31) | 1,291 |
| logdelta (Rust) | 6.87 (15) | 5.25 (20) | 7.02 (15) | 165 |

## Diff of two 100 MB runs (throughput counts both files)

| tool | nginx s (MB/s) | app s (MB/s) | peak MB (max over all runs) |
|---|---:|---:|---:|
| logfold diff 1 thread | 3.32 (63) | 2.88 (73) | 42 |
| logfold diff 16 threads | 0.80 (263) | 0.71 (296) | 107 |
| logfold diff 16 threads, --no-recount | **0.55 (381)** | **0.52 (405)** | 107 |
| logdelta diff (Rust) | 14.74 (14) | 11.67 (18) | 165 |


## Reading the numbers

**Speed-up over Drain3** (median wall time of Drain3 divided by logfold's):

| scenario | nginx | app | loghub |
|---|---:|---:|---:|
| no masking, 1 thread | 8.6× | 12.9× | 16.2× |
| no masking, 16 threads | 15× | 24× | 26× |
| masking, 1 thread | 24× | 25× | 19× |
| masking, 16 threads | 62× | 60× | 36× |

The specification's hypothesis was 20–50×. It holds for masked analysis and for the parallel mode; without masking and in
one thread the gain is 9–16×, because Drain3 itself is cheap when it does no regex work.
`app_100mb` has 1.27 M lines: 0.37 s with 16 threads is about 3.4 M lines/s (target: 1 M lines/s on 8 cores).

**Equivalence of work** (`results/templates.json`, template counts):

| dataset | logfold | Drain3 | logdrain |
|---|---:|---:|---:|
| nginx, masked | 2 | 2 | 2 (`--masks uuid,hex32,ipv4`) |
| app, masked | 12 | 12 | 599 841 |
| loghub, masked | 1 560 | 1 560 | 240 311 |
| nginx, no masks | 2 | 2 | 593 308 |
| app, no masks | 12 | 12 | 599 841 |
| loghub, no masks | 1 867 | 1 866 | 240 310 |

logfold reproduces Drain3's templates (also on all 16 Loghub-2k sets, `eval/results/quality.json`). **logdrain does
different work**: its tokenization keeps path delimiters and does not generalize numeric tokens the way Drain3 does, so on
these inputs it keeps hundreds of thousands of clusters (and more than 1 GB of memory). Its timings are therefore not a
like-for-like comparison, and the library's own figure (1–2 M lines/s per core) was not reproduced through its CLI. The
`logdelta` template count could not be read from its JSON output.

**Diff.** `logdelta diff` took 11.7–14.7 s per pair against 0.7–0.8 s for logfold with the recount pass. The outputs are
not the same (logdelta groups findings into blocks, uses a G-test and several baselines; logfold reports shares and ratios),
so this is a speed comparison of two different reports.

**Memory.** logfold peaks at 93–107 MB with 16 threads and 42 MB with one; Drain3 31 MB; logdelta 9–165 MB; logdrain
over 1 GB. Memory does not depend on the file size for logfold (templates only).

## Limitations

- One machine (Windows 11, i7-10700K, 8 cores / 16 threads), warm page cache, synthetic and Loghub-2k-derived data;
  Loghub-2.0 could not be downloaded.
- `highcard` (about 10⁵ distinct templates, adversarial): logfold 1 thread 4.4 s per 100 MB, 16 threads 8.4 s —
  **chunked is slower than sequential here**, because merging chunk trees of 10⁵ templates costs more than it saves. On the
  10 MB variant Drain3 needed 461 s (one run), logfold 2.3 s. The competitors were not measured on `highcard` at 100 MB
  (the run was stopped), and logdrain and logdelta not at 10 MB either.
- Peak memory for the "no masking" table was not measured separately; the column shows the maximum over all runs of the tool.
- Absolute numbers will differ on Linux and with a cold cache.

