# Continuing a saved state in parallel

`analyze --load-state FILE` continues a saved miner. An input of more than one chunk (`--strategy auto`, or `--strategy chunked`)
is continued in parallel: every chunk starts from a copy of the loaded tree (the seed that `--warm-start` otherwise trains on
the first chunk), and the chunks are merged in order. `--strategy sequential` is the exact continuation: it gives the state of
one run over both logs. The parallel one is deterministic (it does not depend on the number of threads) but not identical to it.
This page measures how far apart they are. Command: `python bench/state_parallel.py FILE ... [--chunk-mb N]`.

## Method

For every 100 MB file the first 30 percent of the bytes (cut at a line) are mined sequentially and saved as a binary state;
the other 70 percent are then continued from it twice, sequentially (the reference) and in parallel with 8 MiB chunks, 16
threads. `-f plain`, default masks, one run each, release build, Windows 11, 8 cores / 16 threads, warm cache; the 0.5.0
development code. The slices of HDFS, Spark, Thunderbird and BGL are the first 100 MB of the Loghub-2.0 files.

| input | state templates | sequential: time, templates | parallel: time, templates | records in shared templates | extra templates |
|---|---:|---|---|---:|---:|
| loghub_100mb | 686 | 0.6 s, 1,035 | 0.2 s, 1,035 | 100.00% | 0 |
| app_100mb | 12 | 0.3 s, 12 | 0.1 s, 12 | 100.00% | 0 |
| nginx_100mb | 2 | 0.4 s, 2 | 0.1 s, 2 | 100.00% | 0 |
| HDFS | 18 | 0.3 s, 25 | 0.1 s, 25 | 100.00% | 0 |
| Spark | 113 | 0.5 s, 79 | 0.1 s, 79 | 100.00% | 0 |
| Thunderbird | 399 | 0.5 s, 864 | 0.1 s, 2,068 | 99.47% | 1,485 |
| BGL | 35 | 0.3 s, 34 | 0.1 s, 34 | 100.00% | 0 |

"Records in shared templates" is the share of the records of the sequential run that sit in templates that the parallel run
also has; "extra templates" are the templates that only the parallel run has.

On Thunderbird the chunk size does not close the gap (extra templates: 1,867 at 2 MiB, 1,741 at 4 MiB, 1,485 at 8 MiB,
1,124 at 16 MiB, 1,044 at 32 MiB; shared records 99.51 to 99.60 percent).

## Reading the numbers

- On six of the seven logs the parallel continuation finds **exactly the templates of the sequential one**, with every record
  in the same templates, 3 to 5 times faster (0.5 s against 0.1 s for 70 MB; on logs of gigabytes the gap is seconds).
- On Thunderbird, a log of many rare messages, the chunks open stray templates that cannot be merged back, as with the
  cold chunked strategy (`WARM_START.md`): more than twice the templates, in 0.5 percent of the records. A loaded tree
  removes the serial prefix of `--warm-start` but not this effect.
- So the parallel continuation is the default and the exact one is `--strategy sequential`; the result of a parallel run carries
  a warning that says it was parallel. A parallel continuation that equals the sequential one on every input needs the loaded
  tree to be read-only while chunks are classified and the records that change it to be replayed in order; it is not
  implemented (see ADR-011a).
