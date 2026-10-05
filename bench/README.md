# Benchmarks

| path | what it is |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | the measurement protocol, fixed before the results; datasets, competitors, commands |
| [`RESULTS.md`](RESULTS.md) | all results as tables, generated from `results/` by `tools/report.py` (do not edit by hand) |
| [`docs/`](docs) | text that is not generated: [`NOTES.md`](docs/NOTES.md) is appended to `RESULTS.md`, [`LOGHUB2.md`](docs/LOGHUB2.md) describes the large real logs and their pinned source |
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
| `report.py` | render `results/` into `RESULTS.md` | `python bench/tools/report.py` |
| `competitors/drain3_run.py` | helper that runs Drain3 for `run.py` | |

Quality of the grouping (accuracy against ground truth) is measured separately by `eval/quality.py`.
