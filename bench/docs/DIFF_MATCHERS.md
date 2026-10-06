# Diff matchers on real before/after pairs

Which matcher should `logfold diff` use? Measured on pairs cut from the four large real logs ([`LOGHUB2.md`](LOGHUB2.md))
with [`diff_matchers.py`](../tools/diff_matchers.py). The 0.3.0 evaluation compared `exact`, `token_subset` and `jaccard`, and
`jaccard` has been the default since. 0.4.0 added `jaccard-idf`, `overlap` and `rules`, computed by the Rust core with the
pure-Python implementation as the reference the tests compare against; they were measured the same way, on smaller windows
(see [the 0.4.0 matchers](#the-040-matchers-accuracy)). Raw data: [`diff-matchers.json`](../results/diff-matchers.json)
(0.3.0), [`diff-matchers-window-200k.json`](../results/diff-matchers-window-200k.json) (0.4.0, accuracy) and
[`matcher-scale.json`](../results/matcher-scale.json) (0.4.0, speed of the matcher alone, script
[`matcher_scale.py`](../tools/matcher_scale.py)).

The matchers added in 0.4.0:

| matcher | score | default threshold |
|---|---|---|
| `jaccard-idf` | Jaccard similarity of the sets of words where a word weighs `1 / n`, `n` the number of one-sided templates (of both runs) that contain it | 0.5 |
| `overlap` | `shared words / words of the shorter template`; templates of fewer than three words are never paired | 0.8 |
| `rules` | the pairs of a user file, `<*>` agrees with any token | none |

A matcher only sees the templates that occur in one run. It may pair a template of *before* with one of *after*, so that a
reworded message is compared as one template instead of being reported as one `new` and one `disappeared`. A pair that joins
two different messages hides a real change, which is the worst failure of a diff; a missed pair only adds noise.

## Method

The real logs come without ground truth, so the pairs are built to have one. Windows are the first lines of each log, as many as
fit up to 3 million lines per side (BGL and Thunderbird are shorter: 2.3 and 2.7 million); the 0.4.0 run used 200,000 lines per
side to keep it short.

| pair | built how | truth | what is counted |
|---|---|---|---|
| `stationary` | the window is dealt in blocks of 1,000 lines alternately to *before* and *after* | nothing changed | reported templates (`new` + `disappeared` + `changed`): false alarms, lower is better |
| `adjacent` | two consecutive windows | none (the log drifts) | the same counts, the pairs a matcher made and the time |
| `reworded` | a stationary pair; in *after* one word `W` is changed on every line that has it | every template with `W` has a twin | twins found among the reachable ones; pairs with a wrong partner |

`reworded` has three modes. `swap` replaces `W` by `W_v2` (same length), `extend` by the two tokens `W_v2 extra` (longer), `novel`
rewrites every plain word of the lines that contain `W` into an unrelated one (numbers, addresses and punctuation stay): that is
a different message, so a twin pair in this mode is a **false merge**. Three words `W` per log, picked from the words that occur
on 0.5-20 percent of the lines. A template is *reachable* when its twin exists among the templates of *after* (the miner can
absorb a reworded template into a more general one, then there is nothing left to pair).

Each pair is run two ways. **live**: `diff before.log after.log`, one shared tree and a recount (every record of both logs is assigned to the finished tree); the time is the whole
`diff`, mining included. **saved**: each log analyzed on its own and the two results compared, as `logfold diff before.json
after.json` does; the time is the comparison only.

The 0.3.0 development code (its version string was still 0.2.1) with the defaults (masks on, depth 4, similarity 0.4), native engine, Python 3.13, Windows 11, 8 cores / 16 threads, warm
page cache. Timed runs: median of three.

## False alarms (reported templates, lower is better)

| log | lines per side | pair | live: exact | live: token_subset | live: jaccard | saved: exact | saved: token_subset | saved: jaccard |
|---|---:|---|---:|---:|---:|---:|---:|---:|
| hdfs | 3,000,000 | stationary | 6 | 6 | 6 | 14 | 6 | 9 |
| hdfs | 3,000,000 | adjacent | 10 | 10 | 10 | 26 | 10 | 12 |
| bgl | 2,315,630 | stationary | 57 | 57 | 55 | 95 | 71 | 60 |
| bgl | 2,315,630 | adjacent | 141 | 141 | 138 | 174 | 148 | 144 |
| spark | 3,000,000 | stationary | 29 | 29 | 29 | 71 | 39 | 37 |
| spark | 3,000,000 | adjacent | 56 | 56 | 56 | 117 | 65 | 60 |
| thunderbird | 2,688,059 | stationary | 200 | 200 | **110** | 905 | 796 | **266** |
| thunderbird | 2,688,059 | adjacent | 1387 | 1387 | 1344 | 2061 | 2029 | 1733 |

- **Live** (shared tree, recount): `token_subset` never pairs anything, so it equals `exact`; the recount already puts the lines of a
  generalized template into the general one. `jaccard` changes the result only where hostnames stay literal in the templates
  (Thunderbird: 200 to 110 on the stationary pair) and slightly on BGL.
- **Saved** (separate mining): the matchers matter. Against `exact`, `jaccard` removes 16-71 percent of the alarms and `token_subset`
  2-62 percent. `token_subset` is as good as `jaccard` where the one-sided templates are plain generalizations (HDFS: 6 and 10
  against 9 and 12, slightly better; Spark, BGL: within 11), and far behind it on Thunderbird (796 against 266).

## Rewording (sums over the three words and the four logs)

| source | mode | reachable twins | found: token_subset | found: jaccard | jaccard: mixed up with a reworded sibling | jaccard: joined with a template that is no rewording |
|---|---|---:|---:|---:|---:|---:|
| live | swap | 1 | 0 | 1 | 0 | 0 |
| live | extend | 61 | 0 | **55** | 4 | 0 |
| saved | swap | 73 | 0 | **67** | 5 | 1 |
| saved | extend | 71 | 0 | **61** | 6 | 0 |
| live | novel (a different message) | 57 | 0 false merges | 0 false merges | | |
| saved | novel (a different message) | 73 | 0 false merges | 0 false merges | | |

- `jaccard` found 184 of 206 reachable twins (89 percent) in `swap` and `extend`; `token_subset` found none: a rewording
  changes a literal, and `token_subset` pairs only a literal with a wildcard.
- 15 pairs of `jaccard` joined a template with another reworded one (a sibling that differs in the number of wildcards or in the host
  name, mostly in the BGL `FATAL` family of 45-55 near-identical templates); 1 pair joined a template with one that is no
  rewording of anything. The rest of the missed twins were left unpaired.
- In `novel` (the message rewritten, only numbers and addresses kept) `jaccard` and `token_subset` made 0 false merges out of 130
  reachable templates.

## What the pairs look like

On the live Thunderbird pair `jaccard` made 36-49 pairs; the sampled ones join two catch-all templates of the same family that differ
in the hostname and in the number of free-text wildcards:

```
- <NUM> <NUM>.<NUM> cn12 Nov <NUM> <NUM>:<NUM>:<NUM> cn12/cn12 kernel: <*> <*> <*> <*> <*> <*> <*> <*> <*> <*> <*>
- <NUM> <NUM>.<NUM> an107 Nov <NUM> <NUM>:<NUM>:<NUM> an107/an107 kernel: <*> <*> <*> <*> <*> <*> <*> <*> <*>
```

These are the noise of host-specific templates, not different messages. The samples (20 per matcher and pair) are in the JSON.

## Speed

### Whole `diff`

Whole live `diff` of the adjacent pair (read, mine, recount, compare), median of three, with 16 threads (the default) and with one
thread (`--strategy sequential`, like a small machine):

| log | lines per side | 16 threads: exact | token_subset | jaccard | 1 thread: exact | token_subset | jaccard |
|---|---:|---:|---:|---:|---:|---:|---:|
| hdfs | 3,000,000 | 0.98 s | 1.00 s | 0.97 s | 6.91 s | 6.92 s | 6.92 s |
| bgl | 2,315,630 | 1.23 s | 1.24 s | 1.24 s | 8.22 s | 8.23 s | 8.23 s |
| spark | 3,000,000 | 1.25 s | 1.24 s | 1.24 s | 8.39 s | 8.84 s | 8.78 s |
| thunderbird | 2,688,059 | 1.65 s | 1.58 s | 1.58 s | 10.91 s | 10.79 s | 11.27 s |

The three matchers take the same time. The spread (up to 0.5 s at one thread) is run-to-run noise, not matching: the comparison of
two saved results, where only the matcher differs, takes 0.2 ms (HDFS), 1 ms (BGL, Spark) and `exact` 10 ms, `token_subset` 13 ms,
`jaccard` 30 ms (Thunderbird, 200-300 one-sided templates per side).

### Growth with the number of one-sided templates

The cost grows with the number of templates that occur on one side only. The worst case is a log in which almost every template is
one-sided. Whole `diff` of two saved results, one thread, native engine (`python bench/tools/diff_scale.py --stage NAME --sizes 5000 10000 20000 40000 80000`, best of three):

| templates per run | exact | token_subset | jaccard |
|---:|---:|---:|---:|
| 18,209 | 0.19 s | 0.22 s | 0.26 s |
| 36,320 | 0.38 s | 0.45 s | 0.61 s |
| 72,615 | 0.88 s | 1.09 s | 1.64 s |

### The matcher alone (0.4.0)

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

#### Variants tried for speed

| algorithm | variant | 100,000 templates, sparse / dense | kept |
|---|---|---:|---|
| `rules` | every rule scans all templates with the same token count | 7.1 s / 7.0 s (growth 1.3) | no |
| `rules` | index by token count, position and token, shortest candidate list per rule | 0.41 s / 0.30 s (growth 0.9-1.0) | yes |
| `overlap` | candidates from the prefix of each side against all words of the other | 1.45 s / 10.7 s | no |
| `overlap` | the same with lists kept longest first, so a probe stops where the sizes stop fitting | 1.22 s / 8.2 s | yes |

Both kept variants return exactly the pairs of the plain definition (tests against a quadratic search on random templates).

## The 0.4.0 matchers: accuracy

The method above on the same four real logs (HDFS, BGL, Spark, Thunderbird), with windows of 200,000 lines per side instead of
3,000,000, so there are few *reachable* twins and the rewording counts below are small. Reported templates on saved results (a matcher that pairs more removes more false
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

## Which one to choose

| | exact | token_subset | jaccard (default) |
|---|---|---|---|
| speed | same on real logs; fastest in the worst case (+0 s) | +0.03 s at 18 thousand one-sided templates | +0.07 s at 18 thousand one-sided templates |
| fewer false alarms, live `diff` | - | none (equals `exact`) | only where host names stay in templates (Thunderbird: -45 percent) |
| fewer false alarms, saved results | - | 2-62 percent | 16-71 percent |
| finds a reworded message | no | no (only literal against wildcard) | 89 percent of the reachable ones |
| joins two different messages | never | 0 of 130 in the test | 0 of 130 in the test; 1 pair of 206 with a template that is no rewording |

`jaccard` is the most accurate and costs nothing measurable, so it is the default. Pick `exact` for the plain, strictly literal
comparison (a template either has the same text or it does not), and `token_subset` when you want only the safe merges (one
template generalizes the other) and nothing else.

The 0.4.0 matchers are alternatives, not replacements: neither `jaccard-idf` nor `overlap` beats `jaccard` on these pairs.
`jaccard-idf` is the one to try where `jaccard` joins siblings that differ in a rare word, `overlap` where messages get longer
(it joined different messages in the reworded-all test, so it is the riskiest), and `rules:FILE` where you know the rewording.

## Limits of this evidence

- Four logs, one machine, the first million lines or so of each (200,000 for the 0.4.0 matchers, with five reachable twins per
  mode: their rewording counts show a direction, not a rate). Only Thunderbird has enough one-sided templates to move the live
  counts; the rewording tests have 57-73 reachable twins per cell, mostly from BGL and Thunderbird.
- `novel` keeps the numbers and addresses and replaces all words; a real new message that shares most of its words with an old one
  is harder, and only the adjacent pairs probe that. The 1 pair out of 206 that joined a template with a non-rewording shows
  that `jaccard` can do it.
- No ground truth for the adjacent pairs: the counts show how much a matcher hides, not whether it hid the right things.
- The window pairs are the same log, not two releases of an application. Pairs from real before/after releases would be a better
  test; none is available.
- At 16 threads a `diff` of these windows takes 1.0-1.7 s; the 5-10 s runs are the one-thread ones.

Reproduce: `python bench/tools/download_loghub2.py`, then `python bench/tools/diff_matchers.py` (about 20 minutes: the timed runs
repeat three times, with 16 threads and with one).
