# Benchmarks

| path | what it is |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | the measurement protocol, fixed before the results; datasets, competitors, commands |
| [`RESULTS.md`](RESULTS.md) | all results as tables, generated from `results/` by `tools/report.py` (do not edit by hand) |
| [`docs/`](docs) | text that is not generated: [`NOTES.md`](docs/NOTES.md) is appended to `RESULTS.md`, [`LOGHUB2.md`](docs/LOGHUB2.md) describes the large real logs and their pinned source, [`DIFF_MATCHERS.md`](docs/DIFF_MATCHERS.md) the evaluation of the diff matchers, [`ADAPTIVE.md`](docs/ADAPTIVE.md) the adaptive strategy, [`WARM_START.md`](docs/WARM_START.md) the warm start of the chunked strategy |
| [`tools/`](tools) | the scripts, below |
| [`results/`](results) | raw measurements as JSON, one file per scenario |
| `data/` | generated and downloaded inputs, git-ignored |

## Scripts (`tools/`)

| script | purpose | example |
|---|---|---|
| `gen.py` | generate the seeded datasets | `python bench/tools/gen.py --out bench/data --size-mb 100` |
| `download_loghub2.py` | fetch the four large real logs at the pinned revision | `python bench/tools/download_loghub2.py` |
| `run.py` | speed and memory of logfold and the competitors (`analyze`, `diff`) | `python bench/tools/run.py --repeat 3` |
| `equivalence.py` | number of templates each tool finds, to check that they do the same work | `python bench/tools/equivalence.py --out bench/results/templates.json` |
| `diff_scale.py` | growth of `analyze` result building and of `diff` with the number of templates | `python bench/tools/diff_scale.py --stage native --sizes 5000 10000 20000` |
| `diff_matchers.py` | which `diff` matcher is best: false alarms, rewording and false merges on before/after pairs cut from the large real logs; [`docs/DIFF_MATCHERS.md`](docs/DIFF_MATCHERS.md) | `python bench/tools/diff_matchers.py --window 300000` |
| `adaptive.py` | `--strategy auto` against `chunked` and `sequential`: time and peak memory; [`docs/ADAPTIVE.md`](docs/ADAPTIVE.md) | `python bench/tools/adaptive.py --repeat 3` |
| `warm_start.py` | `--warm-start` of the chunked strategy: stray templates, time and memory against the cold start; [`docs/WARM_START.md`](docs/WARM_START.md) | `python bench/tools/warm_start.py --repeat 3` |
| `report.py` | render `results/` into `RESULTS.md` | `python bench/tools/report.py` |
| `competitors/drain3_run.py` | helper that runs Drain3 for `run.py` | |

Quality of the grouping (accuracy against ground truth) is measured separately by `eval/quality.py`.
