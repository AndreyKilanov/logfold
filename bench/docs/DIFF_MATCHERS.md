# Diff matchers on real before/after pairs

Which matcher should `logfold diff` use: `exact`, `token_subset` or `jaccard`? Measured on pairs cut from the four large real
logs ([`LOGHUB2.md`](LOGHUB2.md)) with [`diff_matchers.py`](../tools/diff_matchers.py). Raw data:
[`results/diff-matchers.json`](../results/diff-matchers.json). The result: `jaccard` is the default since this evaluation.

A matcher only sees the templates that occur in one run. It may pair a template of *before* with one of *after*, so that a
reworded message is compared as one template instead of being reported as one `new` and one `disappeared`. A pair that joins
two different messages hides a real change, which is the worst failure of a diff; a missed pair only adds noise.

## Method

The real logs come without ground truth, so the pairs are built to have one. Windows are the first lines of each log, as many as
fit up to 3 million lines per side (BGL and Thunderbird are shorter: 2.3 and 2.7 million).

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

logfold 0.2.1 defaults (masks on, depth 4, similarity 0.4), native engine, Python 3.13, Windows 11, 8 cores / 16 threads, warm
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

The cost grows with the number of templates that occur on one side only. The worst case is a log in which almost every template is
one-sided; Rust matchers, one thread, `bench/RESULTS.md` (`diff_scale.py`, whole `diff` of two saved results):

| templates per run | exact | token_subset | jaccard |
|---:|---:|---:|---:|
| 18,209 | 0.54 s | 0.60 s | 0.63 s |
| 36,320 | 1.22 s | 1.35 s | 1.49 s |

## Which one to choose

| | exact | token_subset | jaccard (default) |
|---|---|---|---|
| speed | same on real logs; fastest in the worst case (+0 s) | +0.06 s at 18 thousand one-sided templates | +0.09 s at 18 thousand one-sided templates |
| fewer false alarms, live `diff` | - | none (equals `exact`) | only where host names stay in templates (Thunderbird: -45 percent) |
| fewer false alarms, saved results | - | 2-62 percent | 16-71 percent |
| finds a reworded message | no | no (only literal against wildcard) | 89 percent of the reachable ones |
| joins two different messages | never | 0 of 130 in the test | 0 of 130 in the test; 1 pair of 206 with a template that is no rewording |

`jaccard` is the most accurate and costs nothing measurable, so it is the default. Pick `exact` for the plain, strictly literal
comparison (a template either has the same text or it does not), and `token_subset` when you want only the safe merges (one
template generalizes the other) and nothing else.

## Limits of this evidence

- Four logs, one machine, the first million lines or so of each. Only Thunderbird has enough one-sided templates to move the live
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
