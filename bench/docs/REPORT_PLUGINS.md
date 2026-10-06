# Report plugins: time and memory on many templates

The built-in reports `github-summary`, `junit`, `chat-message` and `prometheus` are written in Python: they read the public
result model and build text. This page measures what they cost on results with 5, 20 and 100 thousand templates before they ship,
to decide whether any part needs the Rust core. Command: `python bench/reporters.py`.

## Method

The reporters never see the engine, so the results are made in memory: a tiny real diff whose template lists are replaced by
synthetic ones (seeded; a service name, three to eight words and a placeholder per template). In a diff, 60 percent of the
templates are new, 20 percent changed and 20 percent gone; about 18 percent of the new ones (10,840 of 60,000 at 100 thousand) are WARN or ERROR, which `junit` lists one by one. An analysis holds all the templates. Each reporter runs in this process with its default options (`default`) and with
every template asked for (`every template`: `top` as large as the result, no size limit). The time is the best of three runs;
the memory is the peak of the Python allocations (`tracemalloc`) of one more run. `csv`, `json` and `markdown` are measured
the same way for scale: they already write every template.

Machine: Windows 11, 8 cores / 16 threads, 34 GB, Python 3.13. The 0.4.0 development code.

## Results

| reporter | result | default: 5k / 20k / 100k | every template: 5k / 20k / 100k | memory (all) at 100k | output (all) at 100k |
|---|---|---|---|---:|---:|
| `github-summary` | analysis | 4 ms / 23 ms / 103 ms | 17 ms / 88 ms / 415 ms | 33.0 MB | 9.39 MB |
| `github-summary` | diff | 1 ms / 3 ms / 25 ms | 13 ms / 58 ms / 299 ms | 30.3 MB | 8.51 MB |
| `junit` | diff | 12 ms / 50 ms / 222 ms | 31 ms / 130 ms / 646 ms | 65.7 MB | 11.48 MB |
| `chat-message` | analysis | 0 ms / 0 ms / 0 ms | 12 ms / 58 ms / 270 ms | 28.5 MB | 7.91 MB |
| `chat-message` | diff | 1 ms / 5 ms / 28 ms | 9 ms / 35 ms / 186 ms | 17.7 MB | 4.78 MB |
| `prometheus` | analysis | 4 ms / 20 ms / 101 ms | 19 ms / 90 ms / 427 ms | 46.6 MB | 13.93 MB |
| `prometheus` | diff | 1 ms / 4 ms / 10 ms | 28 ms / 112 ms / 548 ms | 112.8 MB | 34.41 MB |
| `markdown` | analysis | 0 ms / 0 ms / 0 ms | 7 ms / 36 ms / 169 ms | 29.7 MB | 8.31 MB |
| `markdown` | diff | 0 ms / 0 ms / 0 ms | 8 ms / 37 ms / 221 ms | 31.1 MB | 8.75 MB |
| `csv` | analysis | 22 ms / 103 ms / 468 ms | 22 ms / 101 ms / 539 ms | 28.2 MB | 11.23 MB |
| `csv` | diff | 16 ms / 78 ms / 388 ms | 16 ms / 77 ms / 386 ms | 23.6 MB | 9.39 MB |
| `json` | analysis | 38 ms / 175 ms / 994 ms | 38 ms / 178 ms / 986 ms | 141.9 MB | 40.54 MB |
| `json` | diff | 49 ms / 223 ms / 1,193 ms | 49 ms / 220 ms / 1,272 ms | 185.4 MB | 53.85 MB |

## Reading the numbers

- **Linear growth.** From 5 thousand to 100 thousand templates (20 times) every reporter takes 20 to 25 times longer: no
  quadratic step anywhere. Memory is proportional to the number of templates written.
- **Cheaper than what already exists.** With every template asked for, the new reports take 0.19 to 0.65 s at 100 thousand
  templates, the same order as `csv` (0.4 to 0.5 s) and below `json` (1.0 to 1.3 s). The slowest, `junit` with every template,
  writes an XML element per template.
- **The defaults are almost free.** `github-summary` of a diff lists 20 templates per list and `chat-message` 5: 25 ms and 28 ms at 100
  thousand templates, which is the time to split the new templates into WARN+ and the rest. `prometheus` of a diff writes
  the 50 most frequent templates of each kind: 10 ms.
- **`junit` default is the largest** (222 ms at 100 thousand), because every new WARN+ template is a test case. Here 10,840
  of them fail; a run with that many new alarms is a finding in itself, and 0.2 s is not what makes it slow.
- **About 100 ms of the analysis defaults is not the reporter.** `github-summary` and `prometheus` of an analysis print the
  records per level, which `AnalysisResult.levels` sums over all templates. `markdown`, which does not print it, is at 0 ms.
- **Memory.** The peak with every template is 18 to 66 MB for the text reports and 113 MB for `prometheus` of a diff, which writes
  two series per template. Defaults stay under 1.1 MB, except `junit` (23.5 MB, for its 10,840 failures). `json` needs 142 to 185 MB for the same results.
- Size limits are met by listing fewer templates, not by cutting text: `github-summary` stays under 900,000 bytes (a step
  summary may hold 1 MiB), `chat-message` under 3,000 characters (one Slack section), `prometheus` writes `top` templates
  (50) per section, because the template text is a label and the number of series is the cost on the monitoring side.

## Rust or Python

**Python.** The decision rule of the plugin plan is a measured one: Rust only where a number says the Python is the bottleneck.
It is not: the heaviest realistic case, every one of 100 thousand templates through the heaviest reporter, takes 0.65 s, and the
defaults (what a pipeline runs) take 10 to 220 ms. The work is building strings from fields that are already Python objects
and escaping them. Nothing in a reporter is an algorithm over the templates that Rust would speed up: ranking is a stable split of
an already sorted list, and the only sum over all templates (records per level) belongs to the result model.
