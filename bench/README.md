# Benchmarks

Four scripts; the flags choose what is measured. They print Markdown tables and save the raw numbers of every run to `bench/results/`.

| script | what it does |
|---|---|
| [`data.py`](data.py) | the inputs: `make` writes seeded datasets, `loghub2` downloads the four large real logs |
| [`speed.py`](speed.py) | speed and memory: `analyze` (logfold variants and the competitors), `diff`, `formats` (each built-in format against `plain`), `matchers` (each native matcher alone) |
| [`reporters.py`](reporters.py) | time and memory of the reporters on results with 5, 20 and 100 thousand templates, built in memory |
| [`accuracy.py`](accuracy.py) | which `diff` matcher is best: false alarms, rewording and false merges on before/after pairs cut from the large real logs |

| path | what it is |
|---|---|
| [`PROTOCOL.md`](PROTOCOL.md) | the measurement protocol, fixed before the results; datasets, competitors, commands |
| [`RESULTS.md`](RESULTS.md) | the speed results against the competitors, as they were measured |
| [`docs/`](docs) | the evaluations: [`LOGHUB2.md`](docs/LOGHUB2.md) (large real logs), [`FORMAT_PLUGINS.md`](docs/FORMAT_PLUGINS.md) (the built-in formats), [`REPORT_PLUGINS.md`](docs/REPORT_PLUGINS.md) (the pipeline reporters), [`DIFF_MATCHERS.md`](docs/DIFF_MATCHERS.md) (the matchers), [`ADAPTIVE.md`](docs/ADAPTIVE.md) (`--strategy auto`), [`WARM_START.md`](docs/WARM_START.md) (`--warm-start`) |
| `data/` | generated and downloaded inputs, git-ignored |
| `results/` | the raw numbers of every run, one JSON file per run; created by the scripts, git-ignored |

Quality of the grouping (accuracy against ground truth) is measured separately by `eval/quality.py`.

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
python bench/reporters.py --sizes 5000 20000 100000

python bench/accuracy.py --window 200000 --logs hdfs bgl             # needs the real logs from data.py loghub2
```

`python bench/speed.py analyze --help` lists every flag. The speed of the pure-Python reference engine is not measured.
