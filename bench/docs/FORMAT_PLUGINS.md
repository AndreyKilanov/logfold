# Format plugins: speed against `plain`

The built-in format plugins (`haproxy`, `postgresql`, `postgresql-csv`, `docker-json`, `github-actions`, `log4j`) are
declarative: a regular expression or a list of JSON keys that the Rust engine compiles, so nothing runs per line outside the engine.
This page measures what that costs before a plugin ships: size, time, memory and growth. Script: [`format_plugins.py`](../tools/format_plugins.py).

## Method

For every format a log is generated (seeded, realistic lines: addresses, ids, durations, stack traces and multi-line statements
where the format has them), 10, 100 and 1000 MiB. `logfold analyze FILE -f NAME --top 1 -q` runs as a separate process
(`run.py` records wall time and peak working set) with the format and with `-f plain`, which treats every line as a message and
parses nothing: the difference is the price of the format. Defaults otherwise (masks on, strategy `auto`, all threads). Median of
three runs for 10 and 100 MiB, one run for 1000 MiB. The figures are those of the native (Rust) engine.

Every generated log is read in full: 0 unparsed lines and 0 records without a time for all six formats (checked on the 10 MiB
file in the same script).

Machine: Windows 11, 8 cores / 16 threads, warm page cache. The 0.4.0 development code.

## Native engine, MB/s (higher is better)

| format | 10 MiB | 100 MiB | 1000 MiB | `plain` at 1000 MiB | format / `plain` at 1000 MiB | peak memory at 1000 MiB |
|---|---:|---:|---:|---:|---:|---:|
| `haproxy` | 20.1 | 67.3 | 417.9 | 904.7 | 0.46 | 110 MB |
| `postgresql` | 16.3 | 47.4 | 279.1 | 1037.7 | 0.27 | 116 MB |
| `postgresql-csv` | 19.7 | 70.7 | 454.7 | 1182.4 | 0.38 | 110 MB |
| `docker-json` | 21.2 | 84.6 | 456.9 | 1039.7 | 0.44 | 108 MB |
| `github-actions` | 19.0 | 66.2 | 367.0 | 1033.6 | 0.36 | 109 MB |
| `log4j` | 18.7 | 64.7 | about 440 (estimate) | about 1000 | about 0.44 | about 110 MB |

- The `log4j` run on 1000 MiB was stopped to save time. The estimate takes its ratio to `plain` at 100 MiB (0.50) and lowers it by
  12 percent, the average drop of the other five formats between 100 and 1000 MiB (6 to 19 percent), and multiplies by the
  `plain` speed of the other runs (905 to 1182 MB/s). Treat it as 380 to 500 MB/s.
- 10 MiB is dominated by the start of the process (0.35-0.5 s), and 100 MiB still partly by it, so the speed grows with the size;
  the figure that matters for large logs is the 1000 MiB column. The strategy `auto` also switches to chunks and threads for large
  inputs, so the speed is not flat between 10 and 1000 MiB and cannot be extrapolated linearly from the small sizes; the ratio
  to `plain` can.
- Memory is bounded: about 44 MB at 10 MiB and 108-116 MB at 1000 MiB, within 9 MB of `plain`.
- The slowest is `postgresql` (0.27 of `plain`): its prefix is matched by a bounded lazy scan (`.{0,120}?`) up to the level word,
  because `log_line_prefix` differs from site to site. Still 279 MB/s, 1 GB in about 3.7 seconds.

## Against the reference engine

The reference engine is about 100 to 200 times slower on large logs.
