# Report plugins: the Rust renderers on many templates

The built-in reports `github-summary`, `junit`, `chat-message` and `prometheus` are written by the Rust core
(`logfold-core`, `report`); the reporter classes cut the result into columns and make one call. Until 0.5.0 a pure-Python
reporter existed as well, as the reference of the contract and for short listings. This page keeps what was measured when
both existed (the first table), and the current numbers of the single implementation (the second). Command:
`python bench/reporters.py`.

## Method

The reporters never see the engine, so the results are made in memory: a tiny real diff whose template lists are replaced by
synthetic ones (seeded; a service name, three to eight words and a placeholder per template). In a diff, 60 percent of the
templates are new, 20 percent changed and 20 percent gone; about 18 percent of the new ones (10,840 of 60,000 at 100 thousand) are
WARN or ERROR, which `junit` lists one by one. An analysis holds all the templates. Each reporter runs in this process with its
default options (`default`) and with every template asked for (`all`: `top` as large as the result, no size limit). The time is
the best of three runs. The `Rust` time is the whole call a user makes: it includes cutting the result into columns in Python
(about 60 to 100 ms at 100 thousand templates) and handing them over, and the output is the same text byte for byte (checked by
`tests/engines/test_native_reports.py`). `tracemalloc` gives the peak of the Python allocations of one more run; the memory of the
Rust side is not in it.

Machine: Windows 11, 8 cores / 16 threads, 34 GB, Python 3.13, release build of the extension. The 0.4.0 development code.

## Results with both implementations (0.4.0 development code)

| reporter | result | Python, all: 5k / 20k / 100k | Rust, all: 5k / 20k / 100k | Rust is faster by (100k) | default at 100k: Python / Rust |
|---|---|---|---|---:|---|
| `github-summary` | analysis | 17 ms / 71 ms / 367 ms | 8 ms / 35 ms / 195 ms | 1.9x | 91 ms / 143 ms |
| `github-summary` | diff | 13 ms / 53 ms / 292 ms | 4 ms / 17 ms / 124 ms | 2.4x | 19 ms / 76 ms |
| `junit` | diff | 15 ms / 58 ms / 319 ms | 8 ms / 39 ms / 232 ms | 1.4x | 131 ms / 172 ms |
| `chat-message` | analysis | 16 ms / 68 ms / 344 ms | 6 ms / 25 ms / 133 ms | 2.6x | 0 ms / 41 ms |
| `chat-message` | diff | 10 ms / 43 ms / 246 ms | 4 ms / 17 ms / 113 ms | 2.2x | 22 ms / 57 ms |
| `prometheus` | analysis | 27 ms / 136 ms / 590 ms | 8 ms / 41 ms / 240 ms | 2.5x | 90 ms / 158 ms |
| `prometheus` | diff | 35 ms / 140 ms / 736 ms | 6 ms / 31 ms / 193 ms | 3.8x | 10 ms / 94 ms |

For scale, the Python reporters that already write every template take, at 100 thousand templates: `markdown` 0.17 to 0.22 s,
`csv` 0.4 to 0.5 s, `json` 1.0 to 1.3 s.

## Since 0.5.0: Rust only

The Python reporter was removed (the text is held by the golden fingerprints of `tests/fixtures/golden/reports.json`), so a
short listing of a large result also goes through Rust and pays for the columns of every template. Measured with
`python bench/reporters.py --reporter github-summary junit chat-message prometheus` on the machine above (best of three):

| result | reporter | 20k default / all | 100k default / all |
|---|---|---|---|
| analysis | `github-summary` | 19 ms / 29 ms | 115 ms / 165 ms |
| analysis | `chat-message` | 4 ms / 20 ms | 32 ms / 109 ms |
| analysis | `prometheus` | 23 ms / 34 ms | 135 ms / 198 ms |
| diff | `github-summary` | 8 ms / 15 ms | 68 ms / 122 ms |
| diff | `junit` | 23 ms / 29 ms | 149 ms / 199 ms |
| diff | `chat-message` | 6 ms / 17 ms | 52 ms / 98 ms |
| diff | `prometheus` | 8 ms / 24 ms | 85 ms / 167 ms |

Against the table above, a short listing (`default`) of 100 thousand templates costs up to 75 ms more than the Python path did
(`prometheus` of a diff: 10 ms before, 85 ms now); with every template listed the Rust path is faster, as before. A result of
20 thousand templates or less pays 23 ms at most. The next gain is the one named at the end of this page: read the fields in
Rust straight from the objects of the result, and pass only the rows a report lists.

## Reading the numbers

- **Linear growth** in both: from 5 to 100 thousand templates (20 times) the time grows 20 to 30 times; no quadratic step.
- **With every template listed Rust is 1.4 to 3.8 times faster**, and at 100 thousand templates every report is done in 0.11 to
  0.24 s. The gain is not larger because a part of the Rust time is not Rust: the columns are cut from Python objects, 54 to 101
  ms for 100 thousand templates (measured apart from the call). The call itself, which reads the columns and writes the text,
  takes 20 to 60 ms for the short listings and 125 ms for the largest text of 34 MB (`prometheus` of a diff, 200 thousand
  series).
- **With a short listing Rust loses**: `top` 20 or 50 of 100 thousand templates takes 0 to 130 ms in Python and 40 to 170 ms in
  Rust, because the columns of every template are cut anyway while Python needs only the rows it lists. So 0.4.0 sent a
  result to Rust only when at least 1,000 templates were listed and at least an eighth of the templates of the result
  (`report_data.MIN_LISTED`, `LISTED_FRACTION`); otherwise Python rendered, with the same text. Both are gone since 0.5.0.
- **Memory**: the Python allocations of the Rust path are 35 to 50 percent of the Python path with every template
  listed (`prometheus` of a diff: 39 MB against 113 MB). The Rust side holds the rows (borrowed strings, no copy of the texts) and
  the output.
- The numbers of the Python reference changed with this work: `junit` with every template took 0.65 s when it built the XML
  with `xml.etree` and takes 0.32 s with the writer that Rust and Python now share.

## Where the next gain is

The floor of the Rust path is the conversion of the result into columns. The next step, when a report needs it, is to read the
fields in Rust straight from the objects of the result (`getattr` per field instead of a Python list per column), which
removes most of the 60 to 100 ms, and to pass only the rows a report lists. That would also make short listings pay. It needs no
change of the contract in section 12: the text stays the same.
