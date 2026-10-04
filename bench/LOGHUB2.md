# Large real logs: Loghub-2.0

How logfold behaves on four multi-gigabyte real logs, measured with the benchmark protocol ([`PROTOCOL.md`](PROTOCOL.md)).
Only logfold is measured here; the competitors are not (Drain3 needs minutes per gigabyte). Raw data:
[`results/loghub2/`](results/loghub2).

## Source (pinned)

- **Dataset**: Loghub-2.0. The official copy is on Zenodo: <https://zenodo.org/record/8275861>.
- **Copy used**: the Hugging Face dataset `bolu61/loghub_2` (an unofficial upload of the same files: plain text, one log line
  per line, **no ground truth**) at the pinned revision **`4a98d3eb30522891b340609d17fa34709a1d44d2`**.
- **Pinned in code**: `REVISION` and `PINNED_FILES` (size and SHA-256 of every file) in
  [`download_loghub2.py`](download_loghub2.py). Downloads come from that revision and are checked against the pinned values;
  `python bench/download_loghub2.py --verify` checks the files you already have.
- **Verified on 2026-10-04**: size and SHA-256 of the four local files equal the pinned values.
- **To cite**: Z. Jiang et al., *A Large-scale Evaluation for Log Parsing Techniques: How Far are We?*, ISSTA 2024
  ([arXiv:2308.10828](https://arxiv.org/abs/2308.10828)); J. Zhu et al., *Loghub: A Large Collection of System Log Datasets
  for AI-driven Log Analytics*, ISSRE 2023 ([arXiv:2008.06448](https://arxiv.org/abs/2008.06448)).
- **Use**: the upload states no licence. The data is used for research with attribution to the Loghub authors, stays local
  (`bench/data/` is git-ignored) and is not redistributed by this repository.

## The files

| file | repository path | size, bytes | lines | bytes per line | SHA-256 |
|---|---|---:|---:|---:|---|
| bgl | `data/bgl.txt` | 719,447,452 | 4,631,261 | 155 | `1bd8cb4a8b163b5085d21d8e0d4cd844e01748cdcc0888c6380e0fb34ca85591` |
| hdfs | `data/hdfs.txt` | 1,565,682,217 | 11,167,740 | 140 | `e8987f909b97ce975d65f773a4e1eae7aadab455a38db2aa29ed30ae8b96f166` |
| spark | `data/spark.txt` | 1,629,352,119 | 16,075,117 | 101 | `74da349d7202a13194aa02ca2dd0ccb18a130656d002b94eb6b0e78e92bf6823` |
| thunderbird | `data/thunderbird.txt` | 886,308,864 | 5,376,118 | 165 | `29847ee32db96aab25e10ddc0b7f119a7932e2a00fa23a0d1e106da6db1a1d42` |

All four are read with `-f plain` (no built-in format matches them), whole file, with no unparsed lines.

| file | first line |
|---|---|
| bgl | `- 1117838570 2005.06.03 R02-M1-N0-C:J12-U11 2005-06-03-15.42.50.363779 R02-M1-N0-C:J12-U11 RAS KERNEL INFO instruction cache parity error corrected` |
| hdfs | `081109 203518 143 INFO dfs.DataNode$DataXceiver: Receiving block blk_-1608999687919862906 src: /10.250.19.102:54106 dest: /10.250.19.102:50010` |
| spark | `17/03/14 21:40:22 INFO executor.CoarseGrainedExecutorBackend: Registered signal handlers for [TERM, HUP, INT]` |
| thunderbird | `- 1131523501 2005.11.09 aadmin1 Nov 10 00:05:01 src@aadmin1 in.tftpd[14620]: tftp: client does not accept options` |

## How it was measured

- Command (16 threads, no masks): `python.exe -m logfold analyze bgl.txt -f plain --top 1 -q --engine native --no-masks --strategy chunked --threads 16 --chunk-mb 8`; with masks the `--no-masks` flag is dropped; the 1-thread runs use
  `--strategy sequential` (`python.exe -m logfold analyze bgl.txt -f plain --top 1 -q --engine native --strategy sequential`).
- Harness: `python bench/run.py --files bench/data/loghub2/{bgl,hdfs,spark,thunderbird}.txt --label-prefix loghub2: --scenario analyze-bare analyze-masked --skip drain3 logdrain logdelta --repeat 3`.
- Each command runs as a separate process, three repeats, the median is reported (wall time, CPU time, peak working set of
  the process tree). Tree depth 4, similarity threshold 0.4 (defaults), chunk size 8 MiB, native engine, standard output
  discarded.
- logfold 0.2.0, Python 3.13.0, Windows-11-10.0.26200-SP0, 8 physical / 16
  logical cores, 34.2 GB RAM (the machine of the other results). Warm page cache.

## Results

### No masking

| file | 1 thread | 16 threads | speed-up | range (min-max), 16 threads | CPU, 16 threads | peak memory, 1 / 16 threads |
|---|---:|---:|---:|---:|---:|---:|
| bgl | 5.14 s (140 MB/s) | **0.68 s (1,051 MB/s)** | 7.5x | 0.68-0.69 s | 4.2 s | 46 / 112 MB |
| hdfs | 4.85 s (323 MB/s) | **0.93 s (1,683 MB/s)** | 5.2x | 0.93-0.95 s | 7.9 s | 44 / 110 MB |
| spark | 18.69 s (87 MB/s) | **1.28 s (1,278 MB/s)** | 14.7x | 1.24-1.29 s | 11.8 s | 46 / 115 MB |
| thunderbird | 69.65 s (13 MB/s) | **1.86 s (477 MB/s)** | 37.5x | 1.85-1.93 s | 10.8 s | 54 / 134 MB |

### With masking (logfold default rules)

| file | 1 thread | 16 threads | speed-up | range (min-max), 16 threads | CPU, 16 threads | peak memory, 1 / 16 threads |
|---|---:|---:|---:|---:|---:|---:|
| bgl | 5.36 s (134 MB/s) | **1.05 s (685 MB/s)** | 5.1x | 1.04-1.08 s | 9.6 s | 45 / 110 MB |
| hdfs | 10.60 s (148 MB/s) | **1.66 s (944 MB/s)** | 6.4x | 1.66-1.67 s | 19.5 s | 45 / 110 MB |
| spark | 17.22 s (95 MB/s) | **2.01 s (811 MB/s)** | 8.6x | 2.00-2.04 s | 24.0 s | 45 / 111 MB |
| thunderbird | 32.08 s (28 MB/s) | **1.33 s (665 MB/s)** | 24.1x | 1.33-1.34 s | 13.8 s | 47 / 118 MB |

## Template counts: the work is not identical

The speed of the parallel mode has to be read next to what it returns. The sequential mode builds one tree (the reference
result); the parallel mode builds one tree per 8 MiB chunk and merges them.

| file | masked, 1 thread | masked, 16 threads | no masks, 1 thread | no masks, 16 threads |
|---|---:|---:|---:|---:|
| bgl | 156 | 158 | 647 | 952 |
| hdfs | 34 | 34 | 43 | 341 |
| spark | 190 | 196 | 1,839 | 4,570 |
| thunderbird | 1,098 | 2,488 | 5,529 | 12,752 |

- With masking the two modes agree closely on `bgl`, `hdfs` and `spark`; on `thunderbird` the parallel mode returns 2.3x more
  templates.
- Without masks the parallel mode returns many more templates (`hdfs` 341 against 43, `spark` 4,570 against 1,839): merging
  the chunk trees joins fewer templates than one tree built over the whole file. Use masking, or the sequential mode, when
  the number of templates matters.
- These files have no ground truth in this copy, so grouping accuracy is **not** measured here (it is measured on
  Loghub-2k, `eval/quality.py`).

## Reading the numbers

- Parallel speed-ups are 5x to 37x; the 16-thread mode processes 480-1,700 MB/s without masks and 650-950 MB/s with masks.
- Memory does not follow the input: 44-54 MB with one thread and 110-134 MB with 16 threads for files of 0.7-1.6 GB.
- `thunderbird` is the slow case for one thread: 70 s without masks (13 MB/s) against 32 s with them. It has the most
  templates of the four in the sequential mode (5,529 without masks), which is consistent with the cost per line growing
  with the number of templates a line is compared with (see [High-cardinality data](RESULTS.md#high-cardinality-data));
  this run does not isolate that cause.
- Masks cost time on `bgl` and `hdfs` but save it on `thunderbird`, because they remove most of the distinct templates.

## Limitations

- One machine (Windows 11, 8 cores / 16 threads), warm page cache; Linux and cold-cache numbers will differ.
- Only logfold, only the `analyze` scenarios; no `diff` (these files have no "after" pair).
- No ground truth, so no accuracy figures; the template counts above show how different the outputs are.
- The upload is unofficial; the pinned SHA-256 guarantees the bytes, not that the files equal the Zenodo originals.

## Reproduce

```
python bench/download_loghub2.py hdfs spark thunderbird bgl
python bench/download_loghub2.py --verify
python bench/run.py --files bench/data/loghub2/bgl.txt bench/data/loghub2/hdfs.txt bench/data/loghub2/spark.txt bench/data/loghub2/thunderbird.txt --label-prefix loghub2: --scenario analyze-bare analyze-masked --skip drain3 logdrain logdelta --repeat 3 --out bench/results/loghub2
```
