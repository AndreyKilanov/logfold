# The adaptive strategy

`--strategy auto` (the default) mines an input larger than one chunk in parallel chunks, and merges the chunk trees in order.
Merging is a serial step. On a log in which almost every record is a new template it costs more than the parallel training
saves, and the chunked run is slower and larger than the sequential one. So the first chunk is watched: after its first 10,000
records it holds more than 0.3 templates per record, the chunked run is abandoned (the other chunks are cancelled before
anything is merged) and the whole input is mined with one tree. The result is then the sequential one. Explicit `chunked` and
`sequential` are never changed. The rule is in `docs/ALGORITHM.md` §8.

Measured with [`adaptive.py`](../../tools/adaptive.py) (`python bench/tools/adaptive.py --repeat 3`); raw data
[`results/adaptive.json`](../../results/adaptive.json). `analyze --top 1 -q -f plain --engine native`, masks on, 16 threads, each
command in its own process, median of three runs, peak working set of the process tree. The 0.3.0 development code (its version string was still 0.2.1),
Windows 11, 8 cores / 16 threads, warm page cache. "Chunked" is what `auto` did before.

| input | chunk | `auto` chose | chunked | auto | sequential | chunked MB | auto MB | sequential MB |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| highcard 10 MB | 8 MiB | sequential | 2.02 s | 1.79 s | 1.65 s | 302 | 260 | 258 |
| highcard 100 MB | 8 MiB | sequential | 7.16 s | 4.22 s | 3.78 s | 1889 | 553 | 284 |
| highcard 100 MB (default chunk) | 64 MiB | sequential | 4.17 s | 3.82 s | 3.65 s | 624 | 286 | 284 |
| generated Loghub-like 100 MB | 8 MiB | chunked | 0.57 s | 0.52 s | 1.35 s | 128 | 125 | 66 |
| HDFS 1.6 GB | 8 MiB | chunked | 1.28 s | 1.20 s | 7.13 s | 108 | 107 | 43 |
| BGL 0.7 GB | 8 MiB | chunked | 0.91 s | 0.88 s | 4.65 s | 108 | 108 | 43 |
| Spark 1.6 GB | 8 MiB | chunked | 1.68 s | 1.75 s | 13.05 s | 109 | 109 | 43 |
| Thunderbird 0.9 GB | 8 MiB | chunked | 1.06 s | 1.01 s | 6.29 s | 115 | 115 | 45 |

- On the log of unique messages `auto` takes 4.2 s and 553 MB instead of 7.2 s and 1.9 GB (8 MiB chunks), and 3.8 s and 286 MB
  instead of 4.2 s and 624 MB with the default chunk. It stays 0.2-0.4 s and up to 270 MB above the sequential run: the chunks
  that were already read when the first one decided are abandoned.
- On the real logs `auto` keeps the chunked strategy and costs nothing: the times are within the run-to-run noise (Spark 1.68 s
  against 1.75 s), the output is the chunked one, bit for bit.
- The grouping quality does not change: the sequential and the chunked results are the same as before, and `auto` returns one
  of them.

## Where the threshold comes from

`python bench/tools/adaptive.py --extras-only` stores both tables in `results/adaptive.json`.

Templates per record after the first 10,000 records (sequential, masks on / off):

| input | templates per record |
|---|---|
| highcard 10 MB, 100 MB | 1.000 / 1.000 |
| generated Loghub-like | 0.021 / 0.028 |
| Thunderbird | 0.009 / 0.018 |
| Spark | 0.007 / 0.016 |
| HDFS | 0.001 / 0.001 |
| BGL | 0.001 / 0.001 |

Generated logs of 700,000 lines in which a share of the lines is unique (no masks, 8 MiB chunks, 16 threads):

| share of unique lines | sequential | chunked |
|---:|---:|---:|
| 2 % | 0.71 s | 0.26 s |
| 10 % | 1.67 s | 1.01 s |
| 25 % | 2.85 s | 2.02 s |
| 50 % | 3.74 s | 3.39 s |
| 100 % | 4.70 s | 5.27 s |

Chunked wins until about half of the records are new, and its memory grows with the share. The threshold 0.3 templates per record
sits above every real log (at most 0.03) and below the break-even, so the chunked run is given up only when the merge dominates.

## Limits

- The decision is taken from the first chunk, in both directions. A log that is repetitive at the start and unique later stays
  chunked (slower and larger, as before). A log that starts with more than 10,000 records of unique messages (a long dump at
  the start) and is repetitive afterwards is mined sequentially, which takes 4-8 times longer than the chunked run would
  (HDFS: 7.1 s against 1.3 s); pass `--strategy chunked` for such logs.
- The merged chunk trees still hold more templates than the sequential tree on logs without masks (HDFS without masks: 341
  against 43); that is the over-splitting of the merge and is not changed here.
