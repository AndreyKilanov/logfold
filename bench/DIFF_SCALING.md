# How `diff` and result building scale with the number of templates

Script: [`diff_scale.py`](diff_scale.py), raw data: [`results/diff-scale-before.json`](results/diff-scale-before.json) and
[`results/diff-scale.json`](results/diff-scale.json).

Large inputs are slow to measure, so the script runs small sizes (5, 10 and 20 thousand lines per run, which give about
4.6, 9.1 and 18.2 thousand templates), takes the best of three repeats for the fast measurements, fits the growth
exponent `t ~ n^k` between the smallest and the largest size and extrapolates. A matcher whose projected time is above the
budget (120 s) is skipped at the larger sizes. One thread, native engine, Windows 11, Python 3.13.

Both runs are analyzed first; the table times `diff` of the two saved results. `analyze_engine_s` is the time inside the
engine, `analyze_s` the whole call.

## Before: the matchers compared every pair of templates

| lines | templates | analyze_s | analyze_engine_s | diff exact (s) | diff token_subset (s) | diff jaccard (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 5,000 | 4,571 | 0.08 | 0.03 | 0.13 | 4.67 | 18.93 |
| 10,000 | 9,122 | 0.15 | 0.06 | 0.26 | 18.39 | 77.26 |
| 20,000 | 18,209 | 0.32 | 0.14 | 0.58 | 81.20 | skipped |

Growth exponents: `token_subset` 2.07, `jaccard` 2.04, that is x4 time for x2 templates. Projected at 54 thousand
templates: `token_subset` 767 s, `jaccard` 2,883 s.

## After: candidates come from an index

`token_subset` looks up templates of the same token count that hold the same literal token or a wildcard at one position;
`jaccard` uses prefix filtering (words ordered from the rarest, only templates that share a rare word are scored). Both
return exactly the pairs of the earlier implementations (differential tests in `tests/api/test_matchers.py`).

| lines | templates | analyze_s | analyze_engine_s | diff exact (s) | diff token_subset (s) | diff jaccard (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 5,000 | 4,571 | 0.08 | 0.03 | 0.12 | 0.15 | 0.25 |
| 10,000 | 9,122 | 0.15 | 0.07 | 0.25 | 0.32 | 0.69 |
| 20,000 | 18,209 | 0.32 | 0.14 | 0.57 | 0.74 | 2.20 |

Growth exponents: `token_subset` 1.16, `jaccard` 1.57. Projected at 54 thousand templates: `token_subset` 2.6 s, `jaccard`
12 s; at 100 thousand: 5.4 s and 32 s.

## After: the matchers run in Rust

`token_subset` and `jaccard` are also implemented in `logfold-core` and called once per pair of template lists through
`logfold._core.match_templates`; the Python versions are the reference and the fallback. Raw data:
[`results/diff-scale-native.json`](results/diff-scale-native.json); the sizes go up to 80 thousand lines.

| lines | templates | analyze_s | analyze_engine_s | diff exact (s) | diff token_subset (s) | diff jaccard (s) |
|---:|---:|---:|---:|---:|---:|---:|
| 5,000 | 4,571 | 0.08 | 0.03 | 0.12 | 0.14 | 0.15 |
| 10,000 | 9,122 | 0.16 | 0.07 | 0.26 | 0.28 | 0.34 |
| 20,000 | 18,209 | 0.32 | 0.14 | 0.54 | 0.61 | 0.81 |
| 40,000 | 36,320 | 0.70 | 0.31 | 1.23 | 1.36 | 2.31 |
| 80,000 | 72,615 | 1.66 | 0.77 | 2.62 | 2.93 | 7.22 |

Growth exponents: `token_subset` 1.11, `jaccard` 1.39. Projected at 100 thousand templates: 4.2 s and 11 s.

The matching itself is the difference to `diff exact` (the join and the comparison, which are still Python): at 18
thousand templates `token_subset` costs 0.17 s in Python with the index and 0.07 s in Rust, `jaccard` 1.63 s and
0.27 s. The rest of a `diff` is now the join of the two results and the building of the entries.

## What is left

- `diff exact` and `analyze` are linear but slow per template (about 30 microseconds for `diff exact`, 17 for the part of
  `analyze` outside the engine); they are the next target (the join and the entries of `diff`, the conversion of the
  engine result), now the bulk of a `diff`.
- The prefix filter is exact but its cost depends on the data: templates that share many common words and differ in a
  few produce many truly similar pairs, and every such pair is scored, as it was before.
