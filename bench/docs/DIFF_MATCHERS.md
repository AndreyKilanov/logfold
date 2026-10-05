# Diff matchers on real before/after pairs

Which matcher should `logfold diff` use by default: `exact`, `token_subset` or `jaccard`? Measured on pairs cut from the four
large real logs ([`LOGHUB2.md`](LOGHUB2.md)) with [`diff_matchers.py`](../tools/diff_matchers.py). Raw data:
[`results/diff-matchers.json`](../results/diff-matchers.json).

A matcher only sees the templates that occur in one run. It may pair a template of *before* with one of *after*, so that a
reworded message is compared as one template instead of being reported as one `new` and one `disappeared`. A pair that joins
two different messages hides a real change, which is the worst failure of a diff; a missed pair only adds noise.

## Method

The real logs come without ground truth, so the pairs are built to have one.

| pair | built how | truth | what is counted |
|---|---|---|---|
| `stationary` | the first 600,000 lines are dealt in blocks of 1,000 lines alternately to *before* and *after* | nothing changed | reported templates (`new` + `disappeared` + `changed`): false alarms, lower is better |
| `adjacent` | lines 0-300,000 against 300,000-600,000 | none (the log drifts) | the same counts, and the pairs a matcher made |
| `reworded` | a stationary pair; in *after* one word `W` is changed on every line that has it | every template with `W` has a twin | twins found among the reachable ones; pairs that join a template with `W` to something else |

`reworded` has three modes. `swap` replaces `W` by `W_v2` (same length), `extend` by the two tokens `W_v2 extra` (longer),
`novel` rewrites every plain word of the lines that contain `W` into an unrelated one (numbers, addresses and punctuation stay):
that is a different message, so a twin pair in this mode is a **false merge**. Three words `W` per log, picked from the words
that occur on 0.5-20 percent of the lines.

Each pair is run two ways. **live**: `diff before.log after.log`, one shared tree and a recount (ADR-007). **saved**: each log
analyzed on its own and the two results compared, as `logfold diff before.json after.json` does. Only *reachable* templates
count for twins: the miner can absorb a reworded template into a more general one, and then there is nothing left to pair.

Defaults of logfold 0.2.1 (masks on, depth 4, similarity 0.4), native engine, Python 3.13, the machine of the other results.

## False alarms (reported templates, lower is better)

| log | pair | live: exact | live: token_subset | live: jaccard | saved: exact | saved: token_subset | saved: jaccard |
|---|---|---:|---:|---:|---:|---:|---:|
| hdfs | stationary | 7 | 7 | 7 | 15 | 13 | 7 |
| hdfs | adjacent | 15 | 15 | 15 | 21 | 19 | 15 |
| bgl | stationary | 14 | 14 | 14 | 23 | 17 | 17 |
| bgl | adjacent | 29 | 29 | 29 | 40 | 31 | 30 |
| spark | stationary | 20 | 20 | 20 | 54 | 22 | 22 |
| spark | adjacent | 78 | 78 | 78 | 137 | 82 | 82 |
| thunderbird | stationary | 194 | 194 | **92** | 595 | 533 | **226** |
| thunderbird | adjacent | 693 | 693 | 633 | 1066 | 1041 | 813 |

- Live (shared tree, recount): `token_subset` never pairs anything, so it equals `exact` everywhere. The recount already
  puts the lines of a generalized template into the general template. `jaccard` changes the result only on Thunderbird, where
  hostnames stay literal in the templates (`an53 ... an53/an53 kernel: <*> ...`): 194 to 92 alarms on the stationary pair.
- Saved (separate mining): the matchers matter. `jaccard` cuts the alarms by 24-62 percent against `exact`; `token_subset`
  cuts 2-59 percent and is as good as `jaccard` only where the one-sided templates are plain generalizations (spark, bgl).

## Rewording (sums over the three words and the four logs)

| source | mode | reachable twins | found: token_subset | found: jaccard | false merges: token_subset | false merges: jaccard |
|---|---|---:|---:|---:|---:|---:|
| live | swap | 0 | - | - | - | - |
| live | extend | 9 | 0 | **9** | - | 0 |
| live | novel | 5 | - | - | 0 | 0 |
| saved | swap | 12 | 1 | **11** | - | 0 |
| saved | extend | 12 | 0 | **12** | - | 0 |
| saved | novel | 12 | - | - | 1 | 0 |

(Live `swap`: the miner absorbs the swapped word into a wildcard, no reachable twin is left. `novel` has no "found" column:
there the right answer is no pair.) No matcher paired a template that contains `W` with a wrong partner (*misplaced* is 0 in
all runs). `token_subset` joined one rewritten message with its original in `saved`/`novel`; `jaccard` never did.

## What the pairs look like

On the live Thunderbird pair `jaccard` made 56-60 pairs; all of the sampled ones join two catch-all templates of the same
family that differ in the hostname and in the number of free-text wildcards:

```
- <NUM> <NUM>.<NUM> cn12 Nov <NUM> <NUM>:<NUM>:<NUM> cn12/cn12 kernel: <*> <*> <*> <*> <*> <*> <*> <*> <*> <*> <*>
- <NUM> <NUM>.<NUM> an107 Nov <NUM> <NUM>:<NUM>:<NUM> an107/an107 kernel: <*> <*> <*> <*> <*> <*> <*> <*> <*>
```

These are the noise of host-specific templates, not different messages. The samples (20 per matcher and pair) are in the JSON.

## Speed

The cost is in the one-sided templates only. On the real logs above that is 2-320 templates per side, so every matcher
takes microseconds. The worst case is a log in which almost every template occurs on one side only. Rust matchers, one thread,
`bench/RESULTS.md` (`diff_scale.py`, whole `diff` of two saved results):

| templates per run | exact | token_subset | jaccard |
|---:|---:|---:|---:|
| 18,209 | 0.54 s | 0.60 s | 0.63 s |
| 36,320 | 1.22 s | 1.35 s | 1.49 s |

## Limits of this evidence

- Four logs, one machine, the first 600,000 lines of each. Only Thunderbird has enough one-sided templates to move the live
  counts; the rewording tests have 5-12 reachable twins per cell. The false-merge result (0 of 17 for `jaccard`) is a
  small sample, not a proof.
- `novel` keeps the numbers and addresses and replaces all words; a real new message that shares most of its words with an old
  one is harder, and only the adjacent pairs probe that.
- No ground truth for the adjacent pairs: the counts show how much a matcher hides, not whether it hid the right things.
- The window pairs are the same log, not two releases of an application. Pairs from real before/after releases would be a
  better test; none is available.

Reproduce: `python bench/tools/download_loghub2.py`, then `python bench/tools/diff_matchers.py --window 300000` (about two minutes).
