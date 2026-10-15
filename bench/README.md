# Benchmarks

Eight scripts; the flags choose what is measured. They print Markdown tables and save the raw numbers of every run to `bench/results/`.

| script | what it does |
|---|---|
| [`data.py`](data.py) | the inputs: `make` writes seeded datasets, `loghub2` downloads the four large real logs |
| [`speed.py`](speed.py) | speed and memory: `analyze` (logfold variants and the competitors), `diff`, `formats` (each built-in format against `plain`), `matchers` (each native matcher alone) |
| [`new_values.py`](new_values.py) | what `diff --new-values` costs against `diff` on the generated pairs, and a stress log with a request id on every line, on which the position of the users must still be compared whatever the strategy |
| [`reporters.py`](reporters.py) | time and memory of the reporters on results with 5, 20 and 100 thousand templates, built in memory |
| [`stream.py`](stream.py) | the streaming interfaces: `logfold stream` and `logfold.Miner` (`add_many`, `add_lines`, `add_log_message`) against `analyze` and a Drain3 loop on one file; prints a table and does not save the raw numbers |
| [`state_parallel.py`](state_parallel.py) | continuing a saved state in parallel against continuing it sequentially, on 100 MB logs |
| [`accuracy.py`](accuracy.py) | which `diff` matcher is best: false alarms, rewording and false merges on before/after pairs cut from the large real logs |
| [`validate/formats.py`](validate/formats.py) | the built-in formats against real software in Docker (PostgreSQL 13 to 17 so far): the expected numbers come from the program, see [`FORMAT_VALIDATION.md`](docs/FORMAT_VALIDATION.md) |

| path | what it is |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | the measurement protocol, fixed before the results; datasets, competitors, commands |
| [`RESULTS.md`](RESULTS.md) | the speed results against the competitors, as they were measured |
| [`docs/`](docs) | the evaluations: [`LOGHUB2.md`](docs/LOGHUB2.md) (large real logs), [`FORMAT_PLUGINS.md`](docs/FORMAT_PLUGINS.md) (the built-in formats), [`REPORT_PLUGINS.md`](docs/REPORT_PLUGINS.md) (the pipeline reporters), [`DIFF_MATCHERS.md`](docs/DIFF_MATCHERS.md) (the matchers), [`ADAPTIVE.md`](docs/ADAPTIVE.md) (`--strategy auto`), [`WARM_START.md`](docs/WARM_START.md) (`--warm-start`), [`STATE_FILES.md`](docs/STATE_FILES.md) (size and speed of the state files), [`STATE_PARALLEL.md`](docs/STATE_PARALLEL.md) (continuing a state in parallel), [`STREAM.md`](docs/STREAM.md) (`logfold stream` and `Miner`) |
| `data/` | generated and downloaded inputs, git-ignored |
| `results/` | the raw numbers of every run, one JSON file per run; created by the scripts, git-ignored |

Quality of the grouping (accuracy against ground truth) is measured separately by `eval/quality.py`.

## Which numbers are current

Every page says which code it measured and keeps its tables as they were measured. The number mask lost its sign in 0.5.0
(`ALGO_VERSION` 2), which changes the text of some templates and the speed of the default masks by a few percent, so before the 0.5.0 release the
pages that could be affected were measured again where that is cheap (100 MB inputs and 3 million lines per side); the runs of gigabytes are not repeated.

| page | measured with | status for 0.5.0 |
|---|---|---|
| [`RESULTS.md`](RESULTS.md), [`LOGHUB2.md`](docs/LOGHUB2.md) | 0.2.0 and later changes | not repeated (competitors, runs of 0.7 to 1.6 GB); the current speed on 100 MB is in the README |
| [`ADAPTIVE.md`](docs/ADAPTIVE.md), [`WARM_START.md`](docs/WARM_START.md) | 0.3.0 development code | not repeated; the runs without masks, which the README quotes, do not depend on the number mask |
| [`DIFF_MATCHERS.md`](docs/DIFF_MATCHERS.md) | 0.4.0 and 0.5.0 development code | the full-window sweep was run again on 2026-10-15 with `ALGO_VERSION` 2: every count is the same |
| [`FORMAT_PLUGINS.md`](docs/FORMAT_PLUGINS.md), [`REPORT_PLUGINS.md`](docs/REPORT_PLUGINS.md) | 0.4.0 development code | not repeated (the ratio to `-f plain` and the reporters do not depend on the number mask) |
| [`MASK_SETS.md`](docs/MASK_SETS.md) | 0.5.0 development code | repeated on 2026-10-15: costs and accuracy |
| [`STATE_PARALLEL.md`](docs/STATE_PARALLEL.md), [`STREAM.md`](docs/STREAM.md), [`STATE_FILES.md`](docs/STATE_FILES.md) | 0.5.0 development code | `STATE_PARALLEL.md` and `STREAM.md` repeated on 2026-10-15; the sizes of the states depend on the number and the length of the templates, which the mask changes by a few bytes |
| [`FORMAT_VALIDATION.md`](docs/FORMAT_VALIDATION.md) | real programs, 2026-10-14 and 15 | does not depend on the number mask |

## Examples

```
python bench/data.py make --size-mb 100                              # nginx, app, loghub, highcard
python bench/data.py make --size-mb 100 --variant b --only nginx app # the "after" runs of diff pairs
python bench/data.py loghub2 hdfs spark                              # real logs, checked against pinned SHA-256

python bench/speed.py analyze bench/data/nginx_100mb.log             # sequential and chunked, default masks
python bench/speed.py analyze FILE --strategy auto chunked sequential --no-masks
python bench/speed.py analyze FILE --strategy chunked --warm-start --chunk-mb 64
python bench/speed.py analyze FILE --tools drain3 logdrain logdelta  # the competitors, if installed
python bench/speed.py diff bench/data/app_100mb.log bench/data/app_100mb_b.log
python bench/speed.py formats --format haproxy log4j --sizes 10 100
python bench/speed.py matchers --sizes 5000 20000 100000
python bench/new_values.py pairs                                      # diff against diff --new-values
python bench/new_values.py stress --lines 1500000                     # a request id on every line
python bench/reporters.py --sizes 5000 20000 100000
python bench/stream.py run bench/data/app_100mb.log --variants analyze stream add_many add_lines add_log_message drain3

python bench/accuracy.py --window 200000 --logs hdfs bgl             # needs the real logs from data.py loghub2
```

`python bench/speed.py analyze --help` lists every flag.
