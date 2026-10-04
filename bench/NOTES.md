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
