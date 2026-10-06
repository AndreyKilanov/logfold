# Benchmarks

| path | what it is |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | the measurement protocol, fixed before the results; datasets, competitors, commands |
| [`RESULTS.md`](RESULTS.md) | the speed results against the competitors as tables, generated from `results/` by `tools/report.py` (do not edit by hand) |
| [`docs/`](docs) | text that is not generated, by topic, below |
| [`tools/`](tools) | the scripts, below |
| [`results/`](results) | raw measurements as JSON, one file per scenario |
| `data/` | generated and downloaded inputs, git-ignored |

Quality of the grouping (accuracy against ground truth) is measured separately by `eval/quality.py`.

## By topic

| topic | what is measured | script | text | raw data |
|---|---|---|---|---|
| data | the seeded datasets and the four large real logs | `gen.py`, `download_loghub2.py` | [`docs/data/LOGHUB2.md`](docs/data/LOGHUB2.md) | `results/loghub2/` |
| analyze | speed and memory of logfold and the competitors (`analyze`, `diff` of two 100 MB runs); the number of templates each tool finds | `run.py`, `equivalence.py`, `report.py` | [`RESULTS.md`](RESULTS.md), [`docs/NOTES.md`](docs/NOTES.md) (appended to it) | `results/analyze-*.json`, `diff.json`, `templates.json` |
| engine | `--strategy auto` against `chunked` and `sequential`; `--warm-start` of the chunked strategy | `adaptive.py`, `warm_start.py` | [`docs/engine/ADAPTIVE.md`](docs/engine/ADAPTIVE.md), [`docs/engine/WARM_START.md`](docs/engine/WARM_START.md) | `results/adaptive.json`, `warm-start.json` |
| diff | growth of `analyze` result building and of `diff` with the number of templates; which `diff` matcher is best (false alarms, rewording, false merges); the speed of each matcher alone | `diff_scale.py`, `diff_matchers.py`, `matcher_scale.py` | [`docs/diff/DIFF_MATCHERS.md`](docs/diff/DIFF_MATCHERS.md) | `results/diff-scale.json`, `diff-matchers.json`, `diff-matchers-window-200k.json`, `matcher-scale.json` |

## Scripts (`tools/`)

| script | purpose | example |
|---|---|---|
| `gen.py` | generate the seeded datasets | `python bench/tools/gen.py --out bench/data --size-mb 100` |
| `download_loghub2.py` | fetch the four large real logs at the pinned revision | `python bench/tools/download_loghub2.py` |
| `run.py` | speed and memory of logfold and the competitors (`analyze`, `diff`) | `python bench/tools/run.py --repeat 3` |
| `equivalence.py` | number of templates each tool finds, to check that they do the same work | `python bench/tools/equivalence.py --out bench/results/templates.json` |
| `report.py` | render `results/` into `RESULTS.md` | `python bench/tools/report.py` |
| `adaptive.py` | time and peak memory of `--strategy auto`, `chunked` and `sequential` | `python bench/tools/adaptive.py --repeat 3` |
| `warm_start.py` | stray templates, time and memory of `--warm-start` against the cold start | `python bench/tools/warm_start.py --repeat 3` |
| `diff_scale.py` | growth of `analyze` result building and of `diff` with the number of templates | `python bench/tools/diff_scale.py --stage native --sizes 5000 10000 20000` |
| `diff_matchers.py` | false alarms, rewording and false merges of the matchers on before/after pairs cut from the large real logs | `python bench/tools/diff_matchers.py --window 300000` |
| `matcher_scale.py` | time of each native matcher alone on 5, 20 and 100 thousand one-sided templates | `python bench/tools/matcher_scale.py` |
| `competitors/drain3_run.py` | helper that runs Drain3 for `run.py` | |
