# logfold algorithm specification (version 1)

This document is the contract between the Rust engine (`logfold-core`, `logfold-io`, `logfold-engine`) and the
pure-Python reference engine (`logfold.engines.python`). For the sequential strategy both engines must produce
**identical** templates, counts, timestamps, levels and examples. All comparisons use integer arithmetic.

`ALGO_VERSION = 1`. Any change to the rules below bumps it.

## 1. Records

A *run* is an ordered list of input files. A *record* is one logical log entry: a physical line, or several lines when
`multiline` is enabled. Records yield `message` (bytes), optional `timestamp` (microseconds since the Unix epoch, UTC)
and optional `level`.

### 1.1 Framing

- Lines are split on `\n`; one trailing `\r` is removed from each line. A final line without `\n` is a line.
- A line made only of ASCII whitespace is skipped (counted in `lines` only).
- Every non-skipped line counts in `lines`; every line that does not become part of a record counts in `unparsed`.
- Multiline (`multiline = true`): a line *starts a record* if it matches the format's start pattern (the regex format's
  `pattern`; the plain format's `record_start`; for JSON a line whose first non-space byte is `{`). A line that does
  not start a record is appended to the current record as `"\n" + line`. Such lines before the first record start are
  unparsed. Without multiline every non-skipped line is its own record candidate.

### 1.2 Formats

- **plain**: message = the whole record text.
- **json**: the line must be a JSON object, else the line is unparsed. `message` = first present key of
  `message_keys` (default `message`, `msg`, `log`); a string is used as is, other scalar JSON values are rendered
  as compact JSON; a missing message makes the line unparsed. `timestamp` = first present key of `time_keys`
  (default `timestamp`, `time`, `ts`, `@timestamp`): strings go through §1.3 (a string of 1–18 ASCII digits is
  treated as an integer), numbers are epoch seconds (`|v| < 1e11`), milliseconds (`< 1e14`), microseconds
  (`< 1e17`) or nanoseconds (integers use integer arithmetic; floats use `floor(v * scale + 0.5)`). Epoch values are
  absolute, so they count as timezone-aware. `level` = first present key of
  `level_keys` (default `level`, `severity`, `lvl`).
- **regex**: `pattern` is searched in the first line of the record; no match means the line is unparsed (or a
  continuation in multiline mode). Named groups select `message_group`, `time_group`, `level_group`. The message is
  the message group followed by the continuation lines. Without `message_group` the message is the whole first line.

### 1.3 Timestamps

Input text is parsed with `ts_format` when given, else as ISO-8601: `YYYY-MM-DD`, then `T` or space, `HH:MM[:SS]`,
optional fraction (`.` or `,`, 1–9 digits, truncated to microseconds), optional zone (`Z`, `±HH`, `±HHMM`, `±HH:MM`).
Without a zone the time is interpreted as UTC and the run is marked *naive* (`tz_aware = false` unless any record
carried a zone). `ts_format` directives: `%Y %y %m %d %e %H %M %S %f %z %b %B %j %T %%`; any other literal must match.
A timestamp that fails to parse is treated as absent (the record still counts).

### 1.4 Levels

The level text is upper-cased, then mapped: `TRACE`, `DEBUG`, `INFO`, `NOTICE`→`INFO`, `WARN`/`WARNING`→`WARN`,
`ERROR`/`ERR`→`ERROR`, `FATAL`/`CRITICAL`/`CRIT`/`EMERG`/`ALERT`/`PANIC`→`FATAL`. The syslog priorities `0`–`7` map
to FATAL (0–2), ERROR (3), WARN (4), INFO (5–6), DEBUG (7). Anything else is absent. Severity
order: TRACE < DEBUG < INFO < WARN < ERROR < FATAL.

## 2. Masking

The message is rewritten in **one left-to-right pass** by an ordered list of rules. At each position the leftmost match
of any rule wins; among rules matching at the same position the earliest rule wins. The matched text is replaced with
the rule's token and scanning continues after the match (matches never overlap, replaced text is never rescanned). This
is the semantics of the alternation `(rule 1)|(rule 2)|...` with a token per alternative. A rule may not match the
empty string. Inline flags must be scoped (`(?i:...)`) and back-references are unsupported. Default rules, in order
(all ASCII mode: `\d`, `\w`, `\b` are ASCII):

| name | pattern | token |
|---|---|---|
| uuid | `[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}` | `<UUID>` |
| ts | `\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z\|[+-]\d{2}:?\d{2})?` | `<TS>` |
| ip | `\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b` | `<IP>` |
| hex | `\b0[xX][0-9a-fA-F]+\b` | `<HEX>` |
| path | `(?:/[\w.\-]+){2,}` | `<PATH>` |
| num | `\b[+-]?\d+(?:\.\d+)?\b` | `<NUM>` |

## 3. Tokenization

Tokens are maximal runs of bytes that are not delimiters (default delimiters: space, tab, `\n`, `\r`). Delimiters must
be ASCII. Empty messages have zero tokens. A token *has a digit* if it contains an ASCII digit.

## 4. Template tree (Drain-compatible)

Parameters: `depth` (default 4, minimum 3), `sim_th` (default 0.4), `max_children` (default 100), `max_templates`
(default 100000). `WILDCARD = "<*>"`. `th = floor(sim_th * 1e6 + 0.5)` (as IEEE double arithmetic).

`token_layers(n) = 0` if `n = 0`, else `min(depth - 3, n - 1)`.

**Route key.** `key(t) = WILDCARD` if `t` has a digit, else `t`.

**Search (no side effects).** Start at the length node for `n` (none → no leaf). For each of the first
`token_layers(n)` tokens: `node = children[key(t)]` if present, else `children[WILDCARD]` if present, else no leaf.
The final node is the leaf.

**Candidate similarity** of a template `T` against the message tokens `M` (same length `n`):
`exact` = number of positions where `T[i] != WILDCARD` and `T[i] == M[i]`; `params` = number of positions where
`T[i] == WILDCARD`. Wildcards never count as matches (this is the similarity of the original Drain training pass,
`include_params = false` in Drain3). Best candidate = maximal `exact`, then maximal `params`, then the earliest created
cluster. Match if `exact * 1_000_000 >= th * n` (for `n = 0` always match).

**Match.** Template becomes `T'[i] = T[i] if T[i] == M[i] else WILDCARD`. Counts and statistics are added to the
cluster for the record's run.

**No match → insert.** If the number of clusters reached `max_templates`, the record goes to the *overflow cluster*
for length `n` (template = `WILDCARD` repeated `n` times, kept outside the tree, created on demand) and the run is
flagged `overflowed`. Otherwise create a cluster with tokens = `M` and attach it to the leaf found by the insert path:
get or create the length node; then for the first `token_layers(n)` tokens, with `k = key(t)`:

1. `k` in `children` → descend.
2. else `k == WILDCARD` → create `children[WILDCARD]`, descend.
3. else if `WILDCARD` in `children`: if `len(children) < max_children` create `children[k]` and descend, otherwise
   descend into `children[WILDCARD]`.
4. else (no wildcard child yet): if `len(children) + 1 < max_children` create `children[k]` and descend; elif
   `len(children) + 1 == max_children` create `children[WILDCARD]` and descend; else create wildcard and descend.

(`max_children >= 1` is required, so rule 4 always creates a child.) The new cluster is appended to the leaf's
cluster list.

## 5. Statistics per cluster and run

`count`; `first` / `last` = min / max timestamp among records with a timestamp; `levels[6]` counts per known level;
`example` = the raw message (before masking) of the first record of that run, truncated to at most 2000 bytes at a
character boundary after lossy UTF-8 decoding (invalid bytes become U+FFFD).

## 6. Merge (chunked strategy)

`merge(self, other)` processes the clusters of `other` in creation order. For each cluster `c` with tokens `C`:
treat `C` like a message: *search* the leaf, pick the best candidate with `T = candidate`, `M = C` and the scoring
above. If matched: `T' = generalize(T, C)` (position-wise, as in *Match*) and `self`'s statistics absorb `c`'s
(counts and levels add, `first` min, `last` max, `example` kept if present else taken from `c`). Otherwise the cluster
is inserted as in §4 (overflow rule included, carrying all of `c`'s statistics). Overflow clusters of `other` merge into `self`'s overflow cluster of the same length.
Run counters (lines, records, unparsed, bytes) add up.

## 7. Freeze

Clusters are visited in creation order (overflow clusters last, ordered by length). Clusters with the same template
text are combined (counts and levels add, `first` min, `last` max, `example` from the earliest cluster that has one for
that run). `text = " ".join(tokens)` decoded lossily. `id = sha256(text as UTF-8)[:16 hex]`. Output order: total count
descending, then `text` ascending by UTF-8 bytes.

## 8. Chunk ownership (chunked strategy)

A chunk `[s, e)` owns every record whose first line starts at a byte offset in `[s, e)`. A chunk with `s > 0` first
skips to the next line start at or after `s` (when byte `s-1` is `\n`, `s` itself is a line start), then in multiline
mode skips lines until a record start. A chunk keeps consuming lines after `e` (continuation lines, blank lines and, before the first record of a file, unparsed lines) until the next line that starts a record; that line belongs to the next chunk. Compressed files are a
single chunk. Chunk size is fixed by configuration and independent of the thread count; chunk results are merged in
chunk order (files of run 0 first, then run 1). The result is deterministic for a fixed chunk size.

## 9. Recount (diff)

Training assigns each record to the tree *as it was at that moment*, so the same line can land in different clusters
in different runs. With `recount` enabled (the default for `diff`) the statistics gathered while training are
discarded and all inputs are read a second time, in the same order, against the finished tree:

1. The record is masked and tokenized as in training and assigned **without changing the tree**: tree search and best
   candidate exactly as in §4; if that finds no cluster, every cluster with the same token count is scanned in
   creation order with the same scoring and tie-breaks.
2. A record that still matches nothing goes to the *unmatched* template of its token count (`<*>` repeated `n` times)
   and the run is flagged `overflowed`.
3. Statistics (§5) are collected in this pass only. Clusters nobody was assigned to disappear. Freezing follows §7;
   clusters are visited in creation order, then the unmatched templates by length.

Run counters (`lines`, `records`, `unparsed`) come from the training pass. In the chunked strategy the merged tree is
shared read-only by all workers, per-chunk statistics are merged in chunk order (the earlier `example` wins), so the
result stays independent of the thread count. Identical inputs therefore produce identical counts in both runs.


## 10. Diff matchers

After recount (§9) or, for saved results, after joining templates by id, templates that exist in one run only can be
paired by a *matcher* so that a reworded message is compared as one template. The built-in matchers are part of the
contract: the native implementation (`logfold-core`, `compare`) and the pure-Python one (`logfold.comparison.matchers`,
`logfold.plugins.matchers`) must return **identical** pairs, in the same order. Matching does not change mined
templates or counts, so it does not affect `ALGO_VERSION`. It is the one place that uses floating point (`jaccard`).

A template text is split into tokens: `token_subset` splits on the single space character (an empty text has no tokens),
`jaccard` on whitespace as Python's `str.split()` sees it (Unicode `White_Space` plus U+001C to U+001F) and keeps the
set of distinct words.

**`token_subset`.** Templates `x` and `y` with the same token count are compatible when, at every position, `x` has `<*>`
or the same token as `y`, or when `y` has `<*>` or the same token as `x` at every position (one generalizes the other).
Templates of the second run are taken in order. Each takes, among the unused templates of the first run that are
compatible with it, the one with the smallest difference between the numbers of `<*>` tokens and then the smallest
index; if there is none it stays unpaired. The result lists `(index in the first run, index in the second run)` in the
order of the second run. Implementations may find candidates with an index, but must verify each candidate with the rule
above.

**`jaccard`** with a threshold `t`. The score of two templates is `|A ∩ B| / |A ∪ B|` over their sets of words (0 when
both sets are empty). Pairs with a score of at least `t` are ordered by score, highest first, then by index in the first
run, then by index in the second run, and taken greedily when neither template is used yet. The result is sorted by
index in the first run. Implementations may skip pairs that cannot reach `t`: pairs whose sizes give `min / max` below
`t` (the score never exceeds it) and pairs that cannot share `ceil(t * (|A| + |B|) / (1 + t))` words (the bound is lowered
by an epsilon on the safe side). Prefix filtering is exact: with the words
ordered from the least to the most frequent in both runs (ties by code point order), two sets with score at least `t`
share a word among the first `n - ceil(t * n) + 1` words of each (`n` is the size of the set; the ceiling uses an epsilon
of 1e-9 on the safe side). A threshold of zero or less scores every pair.

A matcher that is not built in (a plugin, or a subclass of a built-in one) always runs its own Python code.
