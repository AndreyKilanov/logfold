# Large real logs: Loghub-2.0

How logfold behaves on four multi-gigabyte real logs, measured with the benchmark protocol ([`PROTOCOL.md`](PROTOCOL.md)).
Only logfold is measured here; the competitors are not (Drain3 needs minutes per gigabyte). Raw data:
[`results/loghub2/`](results/loghub2) (current build) and
[`results/loghub2-release-0.2.0/`](results/loghub2-release-0.2.0) (the released 0.2.0, for comparison).

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
- logfold 0.2.0 plus the performance changes of `main` made after it (commit `a2aebc4`), Python 3.13.0,
  Windows-11-10.0.26200-SP0, 8 physical / 16 logical cores, 34.2 GB RAM (the machine of the other results). Warm page
  cache. Measured in a clean virtual environment with no plugin packages installed. The released 0.2.0 was measured
  the same way; its results are kept in `results/loghub2-release-0.2.0/` and compared below.

## Results

### No masking

| file | 1 thread | 16 threads | speed-up | range (min-max), 16 threads | CPU, 16 threads | peak memory, 1 / 16 threads |
|---|---:|---:|---:|---:|---:|---:|
| bgl | 3.29 s (219 MB/s) | **0.69 s (1,049 MB/s)** | 4.8x | 0.67-0.72 s | 4.2 s | 43 / 108 MB |
| hdfs | 5.16 s (303 MB/s) | **0.94 s (1,664 MB/s)** | 5.5x | 0.93-1.00 s | 7.8 s | 42 / 107 MB |
| spark | 9.60 s (170 MB/s) | **1.42 s (1,151 MB/s)** | 6.8x | 1.32-1.46 s | 11.4 s | 43 / 112 MB |
| thunderbird | 6.66 s (133 MB/s) | **1.08 s (820 MB/s)** | 6.2x | 1.07-1.09 s | 8.5 s | 51 / 129 MB |

### With masking (logfold default rules)

| file | 1 thread | 16 threads | speed-up | range (min-max), 16 threads | CPU, 16 threads | peak memory, 1 / 16 threads |
|---|---:|---:|---:|---:|---:|---:|
| bgl | 4.93 s (146 MB/s) | **0.92 s (784 MB/s)** | 5.4x | 0.88-0.94 s | 7.9 s | 42 / 108 MB |
| hdfs | 7.84 s (200 MB/s) | **1.21 s (1,291 MB/s)** | 6.5x | 1.21-1.23 s | 12.6 s | 42 / 107 MB |
| spark | 13.23 s (123 MB/s) | **1.63 s (999 MB/s)** | 8.1x | 1.61-1.67 s | 18.2 s | 42 / 108 MB |
| thunderbird | 6.43 s (138 MB/s) | **1.03 s (859 MB/s)** | 6.2x | 1.03-1.06 s | 9.9 s | 45 / 115 MB |

### Compared with the released 0.2.0

The output is identical in every case (the SHA-256 of all template fields and counters is the same), so these are
speed-ups of the same work. They come from two changes: the index search in large leaves (`perf(core)`, issue #29) and the
default mask scanner (`perf(core)`, issue #31).

| file | mode | 1 thread: 0.2.0 -> now | 16 threads: 0.2.0 -> now |
|---|---|---:|---:|
| bgl | no masks | 5.14 s -> 3.29 s (1.56x) | 0.68 s -> 0.69 s (1.00x) |
| bgl | masks | 5.36 s -> 4.93 s (1.09x) | 1.05 s -> 0.92 s (1.14x) |
| hdfs | no masks | 4.85 s -> 5.16 s (0.94x) | 0.93 s -> 0.94 s (0.99x) |
| hdfs | masks | 10.60 s -> 7.84 s (1.35x) | 1.66 s -> 1.21 s (1.37x) |
| spark | no masks | 18.69 s -> 9.60 s (1.95x) | 1.28 s -> 1.42 s (0.90x) |
| spark | masks | 17.22 s -> 13.23 s (1.30x) | 2.01 s -> 1.63 s (1.23x) |
| thunderbird | no masks | 69.65 s -> 6.66 s (10.46x) | 1.86 s -> 1.08 s (1.72x) |
| thunderbird | masks | 32.08 s -> 6.43 s (4.99x) | 1.33 s -> 1.03 s (1.29x) |

The two entries below 1.00x (hdfs without masks on one thread, spark without masks on 16 threads) are inside the
run-to-run variation of this machine: three repeats of the same command ranged 4.87-5.14 s for hdfs on one thread in a
separate check, and the same case took 4.78 s right after the index change. No reproducible regression was found.

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

- The 16-thread mode processes 820-1,660 MB/s without masks and 780-1,290 MB/s with masks; it is 4.8x to 8.1x faster than
  one thread (Thunderbird, the extreme case with 37x on 0.2.0, is now 6.2x).
- Memory does not follow the input: 42-51 MB with one thread and 107-129 MB with 16 threads for files of 0.7-1.6 GB.
- Since 0.2.0 the slow case `thunderbird` (70 s without masks, 32 s with them on one thread) takes about 6.5 s either way;
  the cause and the fix are in [Why one thread was slow on Thunderbird](#why-one-thread-was-slow-on-thunderbird).
- Masks still cost time on `bgl`, `hdfs` and `spark` (the scanner examines every digit at a word boundary), but they no
  longer make `hdfs` twice as slow: one thread needs 7.8 s with masks against 5.2 s without (10.6 s against 4.9 s on 0.2.0).

## Why one thread was slow on Thunderbird

> **Status: fixed after 0.2.0.** This section describes release 0.2.0, measured with temporary counters in the miner.
> The index lists of the tokens that most templates of a leaf share are no longer walked (issue #29), which brought
> Thunderbird on one thread from 69.7 s to 6.7 s without masks and from 32.1 s to 6.4 s with masks, with identical output.
> The hint about formats that cut the header still helps, but is no longer needed to avoid the slowdown.

One thread needed 5 s for BGL (719 MB) and 70 s for Thunderbird (886 MB) although both are read as `plain` and look alike.
The time per line is not constant: it grows with the number of templates the line has to be compared with. Measured with
temporary counters in the miner (not part of the library), sequential mode:

| file, mode | templates | largest leaf (templates) | posting-list entries walked per line | candidates scored per line | time |
|---|---:|---:|---:|---:|---:|
| bgl, masked | 156 | 9 | 0 (a leaf gets the index from 16 templates) | 0 | 5.4 s |
| bgl, no masks | 647 | 171 | 141 | 46 | 5.1 s |
| thunderbird, masked | 1,098 | 395 | 726 | 117 | 29.1 s |
| thunderbird, no masks | 5,529 | 822 | 1,060 | 419 | 67.7 s |

**How the search works.** The tree routes a line by its token count and, with the default depth 4, by its **first token**
(a token with a digit is routed to the wildcard child). Inside the leaf, the line is compared with the templates that
share at least one token with it, found through an inverted index: for every token of the line the index lists the
templates that hold the same token at the same position, and the lists are walked in full.

**Why Thunderbird is slow.**

1. In `plain` the whole line is the message, and the first token of 99.999% of the Thunderbird lines (5,376,074 of
   5,376,117) is the constant `-` (BGL: 93%), as in `- 1131523501 2005.11.09 aadmin1 Nov 10 00:05:01 src@aadmin1 ...`. The first token does not separate
   anything, so a leaf holds **all templates with the same token count**: only 35-41 leaves for 1,000-5,500 templates,
   up to 822 templates in one leaf.
2. The header fields (unix time, date, host name, user and host) are part of the message. Without masks they fragment the
   templates (5,529 of them), and with masks they still leave tokens such as host names.
3. A token that every template of the leaf shares, `-` in position 0 above all, has an index list **as long as the leaf**,
   and the list is walked for every line. That alone is up to 400-800 entries per line (the size of the largest leaves); together with the other shared tokens
   (month, user and host) it is the 700-1,100 entries per line above, and 117-419 templates are then scored.
4. The cost therefore grows with the number of templates in a leaf (more templates, more entries per line), which is why
   it climbs while the file is read:

| lines read (no masks, `plain`) | 0.5 M | 1 M | 2 M | 3 M | 4 M |
|---|---:|---:|---:|---:|---:|
| templates so far | 2,006 | 4,015 | 4,814 | 5,025 | 5,174 |
| time per line | 4.4 us | 11.1 us | 14.4 us | 13.4 us | 12.7 us |

**Check: cut the useless prefix.** The same first 2 million lines, read with a regex format whose `msg` group starts at the
program name (`^\S+ \d+ \S+ \S+ [A-Za-z]{3} +\d+ \d\d:\d\d:\d\d \S+ (?P<msg>.*)$`), so the first token of the message
mostly tells programs apart:

| 2 M lines, sequential | `plain` (whole line) | prefix cut | change |
|---|---:|---:|---:|
| masked: time | 13.0 s | 2.7 s | 4.8x faster |
| masked: leaves / templates / largest leaf | 35 / 1,085 / 393 | 343 / 752 / 55 | |
| masked: index entries per line | 1,002 | 41 | |
| no masks: time | 29.9 s | 2.4 s | 12x faster |
| no masks: leaves / templates / largest leaf | 35 / 4,814 / 791 | 238 / 768 / 60 | |
| no masks: index entries per line | 1,158 | 19 | |

With the prefix cut the run costs about what BGL costs per byte (330 MB in 2.4 s is 140 MB/s, the speed of the BGL
one-thread run). Both runs were made with the counters built in, so absolute times are slightly higher than in the tables above; the
comparison between the two columns is fair.

**Why the parallel mode gains more than the thread count.** A parallel chunk is 8 MiB, about 50,000 Thunderbird lines. A
chunk tree holds far fewer templates than the tree of the whole file, so its leaves stay small and the cost per line stays at
the cheap end of the curve above. The speed-up of 24x-37x on `thunderbird` is therefore more than the thread count: the single-thread run is
slow for the reason above, not the parallel one. The price is the larger number of templates returned (see above).

**What to do.**

- Give logfold a format that cuts the header: a `regex:` format with a `msg` group (or a format plugin) so that the message
  starts at the informative part.
- Use masking: on 0.2.0 it halved the time here and removed most fragmentation.
- Use the parallel mode (the default above 64 MiB), which avoids the large leaves.
- In the library (done, issue #29): the lists of the tokens that most templates of a leaf share are no longer walked;
  a template that reaches the threshold is still found through the remaining lists and its exact score is completed by
  comparing the skipped positions, so the output is identical to the reference engine (`docs/ALGORITHM.md`).

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
