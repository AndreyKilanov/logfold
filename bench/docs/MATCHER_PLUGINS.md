# The jaccard-idf, overlap and rules matchers: speed and accuracy

Three matchers join `jaccard`, all computed by the Rust core (`logfold-core`, `compare`) with the pure-Python implementation as
the reference that the tests compare against. This page measures what they cost and what they find, and records the variants of
the algorithms that were tried for speed. Scripts: [`matcher_scale.py`](../tools/matcher_scale.py) for speed,
[`diff_matchers.py`](../tools/diff_matchers.py) for accuracy. Raw data: [`matcher-scale.json`](../results/matcher-scale.json),
[`diff-matchers-word.json`](../results/diff-matchers-word.json).

| matcher | score | default threshold |
|---|---|---|
| `jaccard-idf` | Jaccard similarity of the sets of words where a word weighs `1 / n`, `n` the number of one-sided templates (of both runs) that contain it | 0.5 |
| `overlap` | `shared words / words of the shorter template`; templates of fewer than three words are never paired | 0.8 |
| `rules` | the pairs of a user file, `<*>` agrees with any token | none |

## Speed

A matcher sees only the templates that occur in one run, so the input is two lists. Two seeded shapes: `sparse` (a vocabulary of
3000 words, a few templates share a word) and `dense` (300 words, many candidate pairs, a stress case). `n` templates per
side, 3-8 words and a service name per template, best of three runs, native engine, Windows 11, 8 cores / 16 threads;
`rules` has `n / 50` rules (2000 at 100 thousand), each naming one template of each side.

| shape | templates per side | `jaccard` | `jaccard-idf` | `overlap` | `rules` |
|---|---:|---:|---:|---:|---:|
| sparse | 5,000 | 0.014 s | 0.016 s | 0.015 s | 0.027 s |
| sparse | 20,000 | 0.094 s | 0.054 s | 0.087 s | 0.090 s |
| sparse | 100,000 | 1.37 s | 0.33 s | 1.22 s | 0.41 s |
| dense | 5,000 | 0.033 s | 0.012 s | 0.020 s | 0.015 s |
| dense | 20,000 | 0.46 s | 0.053 s | 0.32 s | 0.065 s |
| dense | 100,000 | 10.7 s | 0.28 s | 8.2 s | 0.30 s |

Growth `t ~ n^k` between 5,000 and 100,000 templates: `jaccard-idf` 1.0 (sparse) and 1.0 (dense), `rules` 0.9 and 1.0, `overlap` 1.5 and 2.0, `jaccard` 1.5 and 1.9. A real diff hands a matcher a few hundred to a few thousand one-sided templates; the table is
about the worst case. `jaccard-idf` is the fastest, presumably because its heaviest word, a rare one, leaves few candidates; `overlap`
cannot prune by size (a short template is contained in a long one), so it costs about as much as `jaccard`.

### Variants tried for speed

| algorithm | variant | 100,000 templates, sparse / dense | kept |
|---|---|---:|---|
| `rules` | every rule scans all templates with the same token count | 7.1 s / 7.0 s (growth 1.3) | no |
| `rules` | index by token count, position and token, shortest candidate list per rule | 0.41 s / 0.30 s (growth 0.9-1.0) | yes |
| `overlap` | candidates from the prefix of each side against all words of the other | 1.45 s / 10.7 s | no |
| `overlap` | the same with lists kept longest first, so a probe stops where the sizes stop fitting | 1.22 s / 8.2 s | yes |

Both kept variants return exactly the pairs of the plain definition (tests against a quadratic search on random templates).

## Accuracy

The method of [`DIFF_MATCHERS.md`](DIFF_MATCHERS.md) on the same four real logs (HDFS, BGL, Spark, Thunderbird), with one
difference: the windows are 200,000 lines per side, not 3,000,000, to keep the run short, so there are few *reachable* twins
and the rewording counts below are small. Reported templates on saved results (a matcher that pairs more removes more false
alarms; lower is better when nothing real changed):

| log | pair | `exact` | `jaccard` | `jaccard-idf` | `overlap` |
|---|---|---:|---:|---:|---:|
| hdfs | stationary | 15 | 6 | 6 | 6 |
| bgl | stationary | 24 | 18 | 20 | 17 |
| spark | stationary | 54 | 22 | 22 | 22 |
| thunderbird | stationary | 397 | 138 | 310 | 304 |
| hdfs | adjacent | 17 | 7 | 7 | 5 |
| bgl | adjacent | 40 | 29 | 35 | 31 |
| spark | adjacent | 131 | 82 | 85 | 80 |
| thunderbird | adjacent | 515 | 383 | 505 | 489 |

On live diffs (shared tree and recount) the three give the same counts as `jaccard` within a few templates, except on
Thunderbird (99 for `jaccard`, 123 and 121 for the new ones, stationary pair).

Rewording on saved results, sums over three words and four logs:

| mode | reachable twins | `jaccard`: twin / pairs | `jaccard-idf`: twin / pairs | `overlap`: twin / pairs, mixed up, joined with a non-twin |
|---|---:|---:|---:|---:|
| swap | 5 | 5 / 528 | 5 / 252 | 3 / 277, 2, 2 |
| extend | 5 | 4 / 531 | 3 / 253 | 3 / 283, 2, 2 |
| novel (a different message: any twin pair is a false merge) | 5 | 0 / 526 | 0 / 248 | 0 / 283, 4, 4 |

What it says, with the caveat of five reachable twins per mode:

- `jaccard-idf` finds as many twins as `jaccard` (one fewer in `extend`) and pairs about half as many unrelated templates. It
  never joined two different messages in `novel` mode, but on Thunderbird it leaves many more false alarms than `jaccard`
  (310 against 138 on the stationary pair; the host names that stay in those templates are rare words, which probably
  keeps templates apart that `jaccard` joins).
- `overlap` found fewer twins than `jaccard` (3 of 5 in `swap`; a template of four words with one reworded word scores 0.75,
  below 0.8) and made false merges in `novel` mode (4 of 283 pairs), so it is the riskiest of the three.
- Neither beats `jaccard`, which stays the default. They are alternatives for logs where `jaccard` joins siblings
  (`jaccard-idf`) or where messages get longer (`overlap`), and `rules` covers the rest by hand.
