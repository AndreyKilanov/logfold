# The warm start of the chunked strategy

The chunked strategy mines every chunk with its own tree and merges the trees in order. A chunk tree begins empty, so the first
records of a chunk are generalized before the common templates exist, and the stray templates that result differ from chunk to
chunk and cannot be merged back (`docs/ALGORITHM.md` §6). The parallel result therefore holds more rare templates than the
sequential one, while the large templates are the same. `--warm-start` (`warm_start=True`) trains the first chunk alone and
starts every other chunk from a copy of its tree. It is off by default; the default result of the chunked strategy is unchanged.

Measured with [`warm_start.py`](../tools/warm_start.py) (`python bench/tools/warm_start.py --repeat 3`); raw data
[`results/warm-start.json`](../results/warm-start.json). `analyze --top 1 -q -f plain --engine native --strategy chunked`, 16
threads, each command in its own process (the times include about 0.35 s of start-up), median of three runs, peak working set of
the process tree; the numbers of templates are one run each. The 0.3.0 development code (its version string was still 0.2.1), Windows 11, 8 cores / 16 threads, warm
page cache.

| input | sequential | chunk | cold: templates | warm: templates | cold: time | warm: time | cold: MB | warm: MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| HDFS 1.6 GB, no masks | 43 | 8 MiB | 341 | **45** | 0.91 s | 0.98 s | 107 | 107 |
| HDFS 1.6 GB, no masks | 43 | 64 MiB | 102 | **43** | 0.94 s | 1.12 s | 107 | 107 |
| Spark 1.6 GB, no masks | 1,839 | 8 MiB | 4,570 | 2,119 | 1.19 s | 1.41 s | 113 | 117 |
| Spark 1.6 GB, no masks | 1,839 | 64 MiB | 2,931 | **1,847** | 1.26 s | 1.72 s | 111 | 117 |
| Thunderbird 0.9 GB, no masks | 5,529 | 8 MiB | 12,752 | 9,155 | 0.96 s | 1.13 s | 129 | 178 |
| Thunderbird 0.9 GB, no masks | 5,529 | 64 MiB | 10,686 | 7,356 | 1.16 s | 1.72 s | 110 | 152 |
| Thunderbird 0.9 GB | 1,098 | 8 MiB | 2,488 | 2,257 | 1.06 s | 1.19 s | 115 | 146 |
| Thunderbird 0.9 GB | 1,098 | 64 MiB | 2,032 | **1,192** | 1.17 s | 1.65 s | 102 | 122 |
| Spark 1.6 GB | 190 | 8 MiB | 196 | **190** | 1.60 s | 1.90 s | 109 | 112 |
| Spark 1.6 GB | 190 | 64 MiB | 193 | 189 | 1.82 s | 2.49 s | 109 | 111 |
| BGL 0.7 GB | 156 | 8 MiB | 158 | 158 | 0.90 s | 0.92 s | 108 | 109 |
| BGL 0.7 GB | 156 | 64 MiB | 159 | 158 | 0.94 s | 1.32 s | 86 | 82 |
| generated Loghub-like 100 MB | 1,363 | 8 MiB | 1,364 | 1,363 | 0.55 s | 0.63 s | 125 | 143 |
| generated Loghub-like 100 MB | 1,363 | 64 MiB | 1,364 | 1,363 | 1.08 s | 1.44 s | 73 | 93 |

- **What it fixes.** The excess over the sequential result falls from 341 to 45 templates on HDFS without masks (8 MiB chunks),
  from 102 to 43 with the default chunk, from 2,931 to 1,847 on Spark without masks, from 2,032 to 1,192 on Thunderbird. Logs
  with masks (BGL, Spark, the generated one) hardly have strays, and gain nothing.
- **What it costs.** The first chunk is mined alone while the other threads wait, and every chunk starts with a copy of the
  seed tree. About +7-15 percent of the time with 8 MiB chunks and +20-50 percent with the default 64 MiB (+0.1-0.6 s on these
  files); the memory grows by 0-50 MB where the tree is large (Thunderbird). The prefix is one chunk, so a smaller `--chunk-mb`
  makes it cheaper, and on a larger file the share falls.
- **Where it does not help much.** Thunderbird with masks and 8 MiB chunks (2,488 to 2,257): the seed of one small chunk does not
  hold enough of the templates. A bigger chunk helps more and costs more.

## Limits

- On a log of mostly unique messages (`highcard`, 100 MB, 8 MiB chunks) a *forced* `--strategy chunked --warm-start` takes 8.8 s
  and 2.6 GB against 6.9 s and 1.8 GB cold, because every chunk copies a large seed tree. With the default `--strategy auto` the
  seed is the probe: such a log is given up at once and takes 3.7 s and 271 MB. Use the warm start with `auto`.
- The prefix is a whole chunk and is not shortened; a smaller `--chunk-mb` is the way to make it cheaper.
- The option is not recorded in a saved result.

## What is not changed

- The default (cold) result of the chunked strategy, the sequential strategy, `ALGO_VERSION` (the rules of §4 and the default
  merge of §6 are the same; the warm start is an additional, optional rule). A saved result does not record the option.
- The result is deterministic for a fixed chunk size and does not depend on the thread count (tests).
- With `strategy="auto"` the first chunk is still the one that decides whether to give the parallel run up
  ([`ADAPTIVE.md`](ADAPTIVE.md)); with the warm start it is mined alone first, so a log of unique messages is given up at once.
- The option has no effect on a run that is mined sequentially (the sequential strategy, an input of one chunk, the pure-Python
  engine, which says so in a warning).
