# logfold algorithm specification (version 1)

This document is the contract of the Rust engine (`logfold-core`, `logfold-io`, `logfold-engine`, `logfold-report`). The golden results
in `tests/fixtures/golden` and the property tests of `logfold-tests` hold the sequential strategy to it: the templates,
counts, timestamps, levels and examples are exactly the ones described here. All comparisons use integer arithmetic.

`ALGO_VERSION = 1`. Any change to the rules below bumps it.

## 1. Records

A *run* is an ordered list of input files. A *record* is one logical log entry: a physical line, or several lines when
`multiline` is enabled. Records yield `message` (bytes), optional `timestamp` (microseconds since the Unix epoch, UTC)
and optional `level`.

### 1.1 Framing

- Lines are split on `\n`; one trailing `\r` is removed from each line. A final line without `\n` is a line.
- **Size limits.** The content of a line (after the line feed and one trailing `\r` are removed) is at most 16 MiB
  (`MAX_LINE_BYTES`): a longer line keeps its first 16 MiB, and the rest of it is read and dropped. The lines of the
  stream and their offsets are the same as without the limit. A multi-line record takes a continuation line only while
  the record, counting its first line and the `"\n"` before each appended line, is smaller than 1 MiB
  (`MAX_RECORD_BYTES`); the line that crosses the limit is appended whole, the lines after it are counted in `lines` and
  not kept. Both limits are in bytes, so memory depends on the number of templates and threads, not on the size of the
  input, and every engine and strategy cuts at the same byte.
- A line made only of ASCII whitespace is skipped (counted in `lines` only).
- Every non-skipped line counts in `lines`; every line that does not become part of a record counts in `unparsed`.
- Multiline (`multiline = true`): a line *starts a record* if it matches the format's start pattern (the regex format's
  `pattern`; the plain format's `record_start`; for JSON a line whose first non-space byte is `{`). A line that does
  not start a record is appended to the current record as `"\n" + line`. Such lines before the first record start are
  unparsed. Without multiline every non-skipped line is its own record candidate.

### 1.2 Formats

- **plain**: message = the whole record text.
- **json**: the line must be a JSON object, else the line is unparsed. `message` = first present key of
  `message_keys` (default `message`, `msg`, `log`); a string is used as is except that one line break (`\n` or `\r\n`) at its end is dropped, other scalar JSON values are rendered
  as compact JSON; a missing message makes the line unparsed. `timestamp` = first present key of `time_keys`
  (default `timestamp`, `time`, `ts`, `@timestamp`): strings go through §1.3 (a string of 1–18 ASCII digits is
  treated as an integer), numbers are epoch seconds (`|v| < 1e11`), milliseconds (`< 1e14`), microseconds
  (`< 1e17`) or nanoseconds (integers use integer arithmetic; floats use `floor(v * scale + 0.5)`). Epoch values are
  absolute, so they count as timezone-aware. `level` = first present key of
  `level_keys` (default `level`, `severity`, `lvl`).
  With `join_unterminated` (the `docker-json` format) an entry whose message does not end with a line break is joined
  with the entries that follow it, up to the first one whose message does (a blank line between them is skipped, a line
  that is not an entry ends the group and is unparsed): the record is the messages one after the other, with one line
  break dropped from its end, and has the time and the level of the first entry. The entries of the group are lines
  of the file (`lines` counts them), the group is one record. The end of the input closes an open group.
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

### 2.1 Layers and checks (mask sets)

A rule may carry a **check**, `luhn` or `iban`. A candidate that a rule with a check matches is accepted only when the
check passes; otherwise it counts as no match at that position, and the search goes on from the next byte (so no other
rule is tried at that start position, and the digits of a rejected candidate are left to the later rules).

* `luhn`: the candidate is 13 to 19 digits, spaces and dashes ignored, any other byte refuses it, and the digits pass the
  Luhn checksum.
* `iban`: the candidate without spaces is 15 to 34 ASCII letters and digits, starts with two letters and two digits, and
  moving its first four characters to the end and reading letters as 10 to 35 gives 1 modulo 97.

A list of rules is applied in **two layers** when it ends with the six default rules above, in that order and unchanged:
the rules in front of them are the first layer and the default rules are the second. The first layer is matched in one pass
as described above (leftmost match, earliest rule at the same position, checks). The second layer is then applied to each
piece of text between two matches of the first, as if that piece were the whole message (a match of the first layer is
replaced by its token and its text is not scanned again; a token must not be changed by the default rules, which is checked
when the rules are compiled). A list that does not end with the default rules is one layer, exactly as in §2. Without a first
layer the result is the one of §2. At most 256 rules are allowed, a pattern is at most 4096 bytes, and a rule whose pattern
matches the empty string is refused. An implementation may skip the search of the first layer in a text that holds none of
the literals that every match of its rules must contain (a prefix, `@`, `://`); the result does not change, only the time.

The sets `secrets`, `credentials`, `pii` and `payment` of `logfold.plugins` are first layers of this kind; their rules and their `version` are data
(`python/logfold/plugins/mask_data/`), and `mask_fingerprint(rules)` (SHA-256 of the canonical JSON of the rules, 16 hex
digits) names the rules in a state header and in `logfold masks`. `ALGO_VERSION` does not change: with no first layer nothing
differs from before. The extension contract version 16 added the optional `check` of a rule.


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

### 4.1 Eviction (`on_full = evict`)

An optional policy, off by default (`on_full = pool` is the rule above), that replaces the pooling of *No match → insert*.
Every record is numbered in the order the miner gets it (the *tick*, from 1), and a cluster remembers the tick of the last
record that joined it or created it (`last_used`). When a record needs a new cluster and the number of clusters has reached
`max_templates`:

1. `k = max(1, floor(max_templates / 10))` clusters are chosen, the ones with the smallest `(last_used, id)`.
2. Each chosen cluster is removed: its counts of the current run and the history that a loaded state gave it are absorbed into
   the overflow cluster of its length (created as above when it does not exist), and the run is flagged `overflowed` when it
   had records. The number of removed clusters is counted per run, by the run of the record that needed the room
   (`run.evicted`).
3. The other clusters keep their relative order and are renumbered `0, 1, ...`; the leaves, the indexes and the lists of
   lengths are renumbered the same way. The nodes of the tree, their children and their keys do not change, so a message is
   routed as before.
4. The new cluster is created and attached as above.

So the number of clusters never passes `max_templates`, and the counts of the templates, the overflow clusters included, add
up to the number of records mined. A batch of `k` rather than one is removed so that the cost of renumbering is shared by `k`
new templates. The least recently used cluster depends on the order of every record, so the miner mines with one tree: the
chunked strategy is refused and the adaptive one runs as the sequential one. A state of such a miner stores the order of
`last_used` (the rank of every cluster, §13), so a miner built from it continues exactly like the one that was saved: mining A
and then B from the state of A gives the same state as mining A and B in one run. The policy is part of the fingerprint of the settings (it is left out of it when it is
`pool`, so that the fingerprint of every state and report that was made without it is unchanged); a state mined with another
policy is refused. `ALGO_VERSION` does not change: with `pool` the results are those of §4.

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

**Warm start (optional, off by default).** A chunk tree begins empty, so the first records of a chunk are generalized
before the common templates exist, and the stray templates that result differ from chunk to chunk and cannot be merged back.
With the warm start the first unit is trained alone; its tree is the *seed* `S` (its statistics are kept in the result). Every
other unit starts from a copy of `S` with empty statistics and is trained as in §4. The merge starts from `S` itself.
For a unit tree `U`, in order: each of the first `|S|` clusters of `U` is the seed cluster of the same index; its tokens
are generalized into the merged cluster position by position (a position that differs, or is a wildcard on either side,
becomes a wildcard) and its statistics are absorbed. The other clusters of `U` are merged as above, in creation order.
Overflow clusters merge as above. Without more than one unit the warm start changes nothing. The result is deterministic
for a fixed chunk size and independent of the thread count. The warm start never applies to the sequential strategy, and
the default result of the chunked strategy (cold start) is not changed by its existence, so `ALGO_VERSION` stays.

## 7. Freeze

Clusters are visited in creation order (overflow clusters last, ordered by length). Clusters with the same template
text are combined (counts and levels add, `first` min, `last` max, `example` from the earliest cluster that has one for
that run). `text = " ".join(tokens)` decoded lossily. `id = sha256(text as UTF-8)[:16 hex]`. Output order: total count
descending, then `text` ascending by UTF-8 bytes.

## 8. Chunk ownership (chunked strategy)

A chunk `[s, e)` owns every record whose first line starts at a byte offset in `[s, e)`. A chunk with `s > 0` first
skips to the next line start at or after `s` (when byte `s-1` is `\n`, `s` itself is a line start), then in multiline
mode skips lines until a record start. In a format that joins entries (§1.2) the lines that a chunk skips are those that belong to a record of the previous chunk: when the last entry before `s` has no line break at its end (the chunk looks back up to 64 KiB for it; a longer entry counts as one that ends its line), the chunk skips the lines up to and including the first entry that ends its line, or the first line that is not an entry; the previous chunk reads on after `e` until its open group is closed. A chunk keeps consuming lines after `e` (continuation lines, blank lines and, before the first record of a file, unparsed lines) until the next line that starts a record; that line belongs to the next chunk. Compressed files are a
single chunk. Chunk size is fixed by configuration and independent of the thread count; chunk results are merged in
chunk order (files of run 0 first, then run 1). The result is deterministic for a fixed chunk size.

**Choosing the strategy (`auto`).** Merging chunk trees is a serial step; when almost every record opens a new template it
costs more than the parallel training saves. With `auto`, an input larger than one chunk starts as chunked, and the first
chunk counts its templates: after its first 10 000 records it holds more than 0.3 templates per record, the chunked run is
abandoned and the whole input is mined sequentially (§4), so the result is the sequential one. The decision uses only the
first chunk, never the thread count or the timing, so it is deterministic for a fixed chunk size. A first chunk with fewer
than 10 000 records stays chunked. An explicit `chunked` or `sequential` is never changed. The thresholds are execution
parameters, not part of the mining rules: `ALGO_VERSION` stays.

## 8a. Time window

A run may carry a time window `[since, until)` in microseconds since the Unix epoch, each bound optional. It is applied to
every record after parsing and before masking: a record whose timestamp `t` satisfies `since <= t < until` is processed
as usual; a record with a timestamp outside the window is counted as `out_of_range`; a record **without** a timestamp
(none was read or it could not be parsed) cannot be placed and is counted as `untimed`; neither is masked, assigned,
counted as a record or used for the share denominators. A window without bounds admits every record, with or without a
timestamp, so a run without a window is mined exactly as before and `ALGO_VERSION` does not change. The decision uses the
record alone, never its neighbours, so it is the same for every chunk layout and thread count. Lines are counted as
before (`lines` includes the lines of records that were left out). A timestamp without a zone is the wall-clock time as
written, treated as UTC, the same as in §1.3; a bound with a zone is converted to UTC by the caller.

`diff` of one input cut at `T` is two runs over the same input with the windows `[since, T)` and `[T, until)`, mined with
one tree and recounted as for two files (§9).

## 9. Recount (diff)

Training assigns each record to the tree *as it was at that moment*, so the same line can land in different clusters
in different runs. With `recount` enabled (the default for `diff`) the statistics gathered while training are
discarded and all inputs are read a second time, in the same order, against the finished tree:

1. The record is masked and tokenized as in training and assigned **without changing the tree**: tree search and best
   candidate exactly as in §4; if that finds no cluster, every cluster with the same token count is scored in
   creation order with the same scoring and tie-breaks (an implementation may use an index of the tokens of the
   clusters of that length instead of a scan, as long as the winner is the same; the Rust engine does for lengths with
   16 or more clusters).
2. A record that still matches nothing goes to the *unmatched* template of its token count (`<*>` repeated `n` times)
   and the run is flagged `overflowed`.
3. Statistics (§5) are collected in this pass only. Clusters nobody was assigned to disappear. Freezing follows §7;
   clusters are visited in creation order, then the unmatched templates by length.

Run counters (`lines`, `records`, `unparsed`) come from the training pass. In the chunked strategy the merged tree is
shared read-only by all workers, per-chunk statistics are merged in chunk order (the earlier `example` wins), so the
result stays independent of the thread count. Identical inputs therefore produce identical counts in both runs.

### Match mode

`match` is this pass alone, against the tree of a saved state, with no training before it (`logfold.match`,
`logfold match STATE FILE`). The assignment is steps 1 and 3 above, so a record gets the cluster that §9 gives it and the
result does not depend on the strategy or the thread count. The differences are in step 2 and in the counters:

- A record that matches nothing is **not** turned into a template and the run is **not** flagged `overflowed`; it is
  counted by its token count in `run.unmatched` (`records`, and `by_length` as `(token count, records)` pairs sorted by
  token count). The text of an unmatched record is not kept.
- The run counters (`lines`, `records`, `unparsed`, `out_of_range`, `untimed`) come from this pass, so `records` is the
  sum of the counts of the templates and of `unmatched.records`.
- The state is only read. A state mined with another algorithm version, other masks or other parameters is refused, as
  for `--load-state`. `ALGO_VERSION` does not change: the tree and its assignment are the same.

**Exact rule.** `logfold match --exact`, `match(exact=True)` and `Miner.match_many(exact=True)` replace step 1 with the perfect
match of Drain3: a template fits when every constant token equals the token at its position (a wildcard accepts any token). Every
cluster of the same token count is considered, so the answer does not depend on the shape of the tree; among the fitting clusters
the one with the fewest wildcards wins, then the earliest created. A template with many wildcards can fit a record that the
similarity rule refuses (too few equal tokens), and the other way round, so neither rule includes the other. `ALGO_VERSION`
does not change: the tree and the default rule are the same.

`Miner.match_many` (`Session::match_records`) applies steps 1 and 3 to records given in memory, against the tree of a live
miner: nothing is trained, no counter changes and an open record is not touched, so the answer for a record is the same
whatever the other records of the call are. A record that is blank, cannot be parsed or matches nothing has no template.
The template is named as the miner holds it at that moment, with the identifier `sha256(text)[:16]` of §7.

### Check mode

`check` (`logfold.check`, `logfold check FILE --state MODEL`) is match mode plus one more tree. The records are read once, in
order, and each is assigned by the similarity rule to the tree of the saved state; a record that matches nothing is counted as
in match mode **and** is also added to a second, empty miner with the same parameters and masks (the usual training step of
§4, with `max_templates` and the overflow of §4 as usual). The templates of the second miner, frozen as in §7, are the **new
templates**: a record that fits no template of the state cannot join one of them while it is mined, so none of them has the
text or the identifier of a template of the state, and no template of the state changes its text. The state is only read; a
state mined with `on_full = evict` is refused, because the identifier of a template that is evicted and mined again is not
stable. The memory beyond the loaded tree is the second tree, which `max_templates` bounds. The files are read in one
sequential pass whatever the strategy. `ALGO_VERSION` does not change.

The result also carries the **model**: the templates of the state with the counts, times and levels that the saved runs gave
them (the history of the clusters; clusters of the same text are summed, as in §7; no example). The comparison of the model with
the run (the model is the first run, the matched and the new templates the second) is the one of §11 with the matcher `exact`,
so a template of the model that moved by a significant factor is `changed`, and the new templates are exactly `new`;
`disappeared` is dropped, because a log shorter than the model lacks many of its templates.


## 10. Diff matchers

After recount (§9) or, for saved results, after joining templates by id, templates that exist in one run only can be
paired by a *matcher* so that a reworded message is compared as one template. The built-in matchers are part of the
contract, and `logfold-core` (`compare`) is their only implementation: the classes in `logfold.comparison.matchers` and
`logfold.plugins.matchers` hold the name, the threshold and the rules, and call it. A lone surrogate in a template text
has no UTF-8 form and is read as U+FFFD. Matching does not change mined
templates or counts, so it does not affect `ALGO_VERSION`. It is the one place that uses floating point (`jaccard`, `jaccard-idf`, `overlap`).

A template text is split into tokens: `token_subset` splits on the single space character (an empty text has no tokens),
`jaccard`, `jaccard-idf` and `overlap` on whitespace as Python's `str.split()` sees it (Unicode `White_Space` plus U+001C
to U+001F) and keep the set of distinct words; `rules` splits on the single space character like `token_subset`.

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

**`jaccard-idf`** with a threshold `t` (default 0.5). The words are ranked over the templates handed to the matcher, both
lists together: a word with a smaller number `n` of templates that contain it comes first, ties by code point order. A word
weighs `1 / n` (a correctly rounded division). The score of two templates is `S / U`, where `S` is the sum of the weights of
the words in both sets and `U` the sum of the weights of the words in either set, each summed in rank order starting from
`0.0` with ordinary double additions (0 when `U` is 0). Pairs with a score of at least `t` are ordered by score, highest
first, then by index in the first run, then by index in the second run, and taken greedily as for `jaccard`; the result is
sorted by index in the first run. Skipping is allowed only where it is exact: two sets with a score of at least `t` share
their heaviest common word `x`, and the words of each set from `x` on weigh at least `t` times the weight `W` of the set, so
a set needs to probe only the leading words (heaviest first) whose suffix still weighs at least `t * W * (1 - 1e-9)`; a pair
whose weights `a <= b` give `a < b * t * (1 - 1e-9)` cannot reach `t`. A threshold above 1 or `nan` pairs nothing; zero or
less scores every pair.

**`overlap`** with a threshold `t` (default 0.8). The score of two templates is `|A ∩ B| / min(|A|, |B|)` over their sets of
words. A template with fewer than 3 distinct words is never paired. Pairs with a score of at least `t` are ordered and taken
as for `jaccard`. A pair needs `ceil(t * min(|A|, |B|))` shared words (the bound is lowered by 1e-9 on the safe side), so
it shares a word among the first `n - ceil(t * n) + 1` words (rarest first, ranked as for `jaccard`) of its smaller set,
whichever side that is; implementations may find candidates that way. A threshold above 1 or `nan` pairs nothing; zero or
less scores every pair of eligible templates.

**`rules`** with a list of rules `(left, right)` of template texts (`--matcher rules:FILE`: one rule per line,
`TEMPLATE <=> TEMPLATE`, empty lines and lines starting with `#` ignored, UTF-8, at most 16 MiB). A text is split on the
single space character (an empty text has no tokens); a template and a rule side agree when they have the same token count
and, at every position, equal tokens or `<*>` on either side. Rules are applied in file order, and each rule in two
directions, first with `left` against the first run and `right` against the second, then `right` against the first run and
`left` against the second. For one direction the unused templates of the first run that agree with the first side and the
unused templates of the second run that agree with the second side are each listed in ascending index order and paired
position by position, as many pairs as the shorter list has. Each template is used at most once. The result is sorted by
index in the first run. The `rules` matcher is not selected by name alone, because it needs a file.

The default matcher of `diff` is `jaccard` with the threshold 0.6 (`DiffConfig.matcher`, `--matcher`); `exact` and `token_subset` are
selected by name. Changing the default is a change of the public result, not of the mining algorithm, so `ALGO_VERSION` stays.

A matcher that is not built in (a plugin, or a subclass of a built-in one) always runs its own Python code.

## 11. Comparison (diff)

After recount (§9), or for two saved results, the templates of two runs are classified as *new*, *disappeared*,
*changed* or *unchanged*. The native comparison (`logfold-core`, `compare`) and the Python one
(`logfold.comparison.classify`, which a plugin matcher and a result the extension cannot take, such as a count below 0
or above 2^64 - 1 or a template listed twice in one run, go through) must return **identical** entries, in the same
order, with identical floats (the same IEEE double operations in the same order). It does not change mined templates or counts, so it does not affect
`ALGO_VERSION`.

With several baselines (`diff(before, after, baselines=...)`) the runs are mined and recounted together, then the
baselines are pooled into the first run before anything below: counts, level counts and records are added up, the
first time is the earliest and the last the latest, the example is the first one found. A template that occurs in at
least `min_baselines` baselines (default all) or in none stays; one in some but fewer baselines is left out and, when
the second run has it too, counted as *unchanged*. One baseline is mined and classified exactly as before.

Inputs: for each run its templates with a text and a record count (a template with a count of zero is not part of the
run) and the number of records of the run; the thresholds `threshold_ratio` (at least 1), `min_count` and
`min_new_count`; a matcher (§10).

1. Templates are joined by text (equivalently by id, which is `sha256(text)[:16]`).
2. The templates of each run that have no counterpart, in the order of the input, go to the matcher. Every pair it
   returns is one template that is present in both runs; its text and statistics come from the second run.
3. `share = count / records`, and 0 when the run has no records. `ratio = after_share / before_share` when both counts
   are positive and `before_share` is positive, otherwise there is no ratio.
4. `factor = max(r, 1 / r)` where `r` is the ratio, or 1 when there is no ratio or it is 0.
5. A template present in both runs is *changed* when `max(before_count, after_count) >= min_count` and
   `factor >= threshold_ratio`, otherwise *unchanged* (only counted).
6. A template of the second run without counterpart is *new* when its count is at least `min_new_count`; a template of
   the first run without counterpart is *disappeared* by the same rule.
7. Order: new and disappeared by count, highest first, then by text; changed by `factor`, highest first, then by the
   larger of the two counts, highest first, then by the text of the second run. Texts are compared by code points.
8. An entry carries the id, text, example and timestamps of the second run (of the first run for a disappeared
   template), both counts and shares, the ratio, and the level counts of both runs added up: `levels` lists the levels
   with a positive sum in order of severity and `level` is the most severe of them.

## 12. Pipeline reports

`github-summary`, `junit`, `chat-message` and `prometheus` turn a result into text. The Rust crate
`logfold-report` writes the text; the reporter classes in `logfold.plugins` cut a result into columns and call
it. The text is held by the golden fingerprints in `tests/fixtures/golden/reports.json`. The reports do not change mined
templates or counts, so they do not affect `ALGO_VERSION`. The extension takes the columns of a result in one call,
`render_report(report, data, options)`. A lone surrogate in a text is read as U+FFFD, and a count below 0 or above
2^64 - 1 is a `ConfigError`.

Counts are whole numbers below 2^53 (the shares are computed in double precision from them). A level that is not one of
`TRACE`, `DEBUG`, `INFO`, `WARN`, `ERROR`, `FATAL` is shown as no level. A new template is an *alert* when its level is
`WARN`, `ERROR` or `FATAL`.

**Text from a log** goes through these steps, in this order, and is never written otherwise:

1. *Flatten*: every character in U+0000-U+0008, U+000B-U+001F and U+007F-U+009F becomes `\xNN` (two lower-case hex
   digits); whitespace (Unicode `White_Space`) runs become one space and the ends are trimmed.
2. *Clip* to `width` characters (code points): a longer text keeps `width - 3` characters and ends in `...`, or with *tail*
   starts with `...` and keeps the last `width - 3`.
3. Then the rule of the target: a Markdown *code span* replaces `` ` `` by `'` and is wrapped in backticks; *XML text*
   shows U+FFFE and U+FFFF as `U+XXXX`, and the writer escapes `&`, `<`, `>` (and `"` in an attribute); a Prometheus
   *label value* escapes `\` as `\\` and `"` as `\"`. For `chat-message` the *mention rule* runs first: U+200B goes after
   `<` when `!`, `@` or `#` follows, and after `@` when `channel`, `here`, `everyone` or `all` (ASCII, any case) follows and
   the next character is not an ASCII letter, digit or `_`.

**`github-summary`** with `top` and `max_bytes`: a document of lines; the lists
hold `rows = top` templates (`top` first cut to the length of the longest list); while the UTF-8 size exceeds `max_bytes` and `rows > 0`, `rows` is halved (integer division)
and the document written again, with a final note when `rows < top`. New templates are listed alerts first, each group in
the order of the result. **`junit`**: every alert is a test case that fails, then the first `top` new templates that are not
alerts pass; with none, one passing case. **`chat-message`** with `top` and `max_chars`: the headline lines, then new
templates (analysis: the most frequent) alerts first, each line added while `characters so far + line + 1 + 30 <=
max_chars`, then `... and N more` when some were left out. **`prometheus`**: families in a fixed order, a family with no
sample is left out; per template series are written for the first `top` templates of each list.

The exact lines are those of the Python reporters; a change of a line is a change of this section, of both
implementations and of the contract test (`tests/engines/test_native_reports.py`) in one change.

## 13. State files

A state file saves a miner so that a later run continues from it. It does not change how records are mined, so it does not
affect `ALGO_VERSION`; it adds the extension contract version 8. The engine reads and writes state files.

**Content.** The miner as plain data: the parameters (`depth`, `threshold_micro`, `max_children`, `max_templates`); the
nodes of the tree in the order they were created, each with its children (token, node) ordered by the bytes of the token and
the ids of its clusters in the order they were added; the root node of every message length, ordered by length; the clusters
by id, each with its tokens and its *history*; the overflow cluster of every message length, ordered by length; and, for a miner
that evicts (§4.1) only, the *recency ranks*: for every cluster by id its rank by `last_used` (ties: the earlier created), 0 for
the least recently used, a permutation of `0..clusters`. A history is
the count, the earliest and the latest timestamp (microseconds, `i64::MAX` and `i64::MIN` when none) and the count per level
of all the runs saved so far. **No example message is saved.** A template seen once is its masked line, so its words are in
the file; the values the masks hide are not.

**Continuing.** A miner built from a state has empty statistics: its report counts the records of the new run only, and a
template with no record in the new run is not reported. The state saved after the run holds the history of the earlier runs plus
the counts of this one. Continuing is exact: mining A and then B from the state of A gives the same state as mining A and B in
one run (the sequential strategy, the exact continuation). The chunked strategy, which `auto` chooses for an input of more than
one chunk, continues a state too: every chunk starts from a copy of the loaded tree, which is the seed of §6 without a trained
first chunk, and the chunk trees are merged in order as in §6; the result does not depend on the number of threads but is not
the sequential one (`bench/docs/STATE_PARALLEL.md`). A state saved after a chunked run is valid
and can be continued, but its tree is the one that merging the chunks built, so it is not the file that a sequential run over the
same input saves. The run starts with the overflow flags cleared.

**Checks on loading.** The file is untrusted. The kind and the schema version are read first, so a newer layout is reported as newer whatever else
changed in it. Sizes are checked before memory is allocated (defaults: 1 GiB, 1,000,000
templates, 4,000,000 nodes, 64 KiB per token, 512 MiB of tokens together). A state is refused when the checksum does not match,
the schema is newer than this logfold reads, `algo_version` differs, the fingerprint of the masks and parameters
(`config_hash`, the hash of the mining configuration without the log format) differs from the current run, or the tree is not
a tree the miner builds: the ranks, when there are any, one for every cluster and a permutation of them; parameters in range; at most `max_templates` clusters; no empty token; roots in increasing length; no
node reached twice and none unreachable; an inner node holds no cluster and a leaf no child; at most `max_children` children
ordered by token; a token with a digit is a child only as `<*>`; every cluster is in exactly one leaf of its own length and on
a path its tokens can follow; an overflow cluster is `<*>` repeated to its length.

The header text `masks` is `default` for the default rules and, for any other list, the fingerprint of its rules (§2.1); it
informs, and the check on loading uses `config_hash`, which covers every rule, so the first layer of a mask set is part of what
a state must match.

**JSON form.** Three lines, each ending in a line feed. Line 1, the header, written in this order with no spaces:
`{"kind":"logfold-state","schema_version":1 or 2,"algo_version":..,"contract":..,"logfold_version":"..","config_hash":"..",
"masks":"..","format":"..","miner":{"depth":..,"threshold_micro":..,"max_children":..,"max_templates":..},"counts":{"nodes":..,
"clusters":..,"overflow":..,"token_bytes":..}}`. Line 2, the body:
`{"nodes":[{"c":[[token,child],..],"k":[id,..]},..],"roots":[[length,node],..],"clusters":[{"t":[token,..],"h":[count,first,
last,[level counts]]},..],"overflow":[[length,{"t":..,"h":..}],..]}`, with `,"recency":[rank,..]` before the closing brace in
schema version 2. Line 3: `{"sha256":"<hex>"}`, the SHA-256 of lines
1 and 2 with their line feeds. A token is a JSON string (strings are escaped as `"` `\` and the control characters; other
characters are written as they are), or `{"hex":"<lower-case hex>"}` when its bytes are not UTF-8. Numbers are integers.
`token_bytes` is the number of bytes of the tokens of the clusters, of the overflow clusters and the keys of the children.

**Binary form.** The magic `LFSTATE\0`, the schema version (u16 little-endian), `algo_version` and `contract` (u32 little-endian),
four texts (`logfold_version`, `config_hash`, `masks`, `format`: a varint length and the bytes), the four parameters and the four
counts as varints, the roots (a varint count, then length and node as varints), the nodes (children as token and node, the
ids of the clusters, each list with a varint count), the clusters (a varint token count, each token with a varint length,
the history as a varint count, two little-endian `i64`, six varint level counts), the overflow clusters (length as a varint, then
a cluster), in schema version 2 the recency ranks (one varint for every cluster), and the SHA-256 of all the bytes before it
(32 bytes). A varint is an unsigned LEB128 of at most 64 bits.

**Schema versions.** Version 1 is the layout above without the ranks; it is the only one written for a miner that pools, so
the state of such a miner is the same bytes as before the policy `evict` existed. Version 2 adds the ranks and is written only for
a miner that evicts: a file of version 2 without ranks, or of version 1 with them, is damaged, and a logfold that reads up to
version 1 refuses a file of version 2 as newer.

A file written to a path that ends in `.gz` is compressed with gzip; a gzip file is recognized by its first bytes, whatever its
name, and read with the size limit applied to the decompressed bytes. The same state is the same bytes before
compression (the compressed bytes depend on the compressor, only the content is promised); a change of this layout is a change of this section,
of both implementations and of the contract tests in one change, and raises `schema_version`.

## 14. Parameters of a message

`extract_parameters(template, message)` (`logfold.extract_parameters`, `logfold params`) gives the values that a message has at the
variable positions of a template. It adds no new behavior to mining: it repeats the masking of §2 and the tokenization of §3 and
remembers where each replacement stood in the message.

1. Mask the message as in §2, keeping for every match the rule and its span in the message. The matches are the ones that §2
   replaces (the hand-written scanner of the default rules is tested against the regex engine, which gives the spans).
2. Tokenize the masked text as in §3. The template is the list of its tokens (its text split at single spaces). The message fits
   only if it has the same number of tokens; in the exact fit every constant token of the template must also equal the token of the
   message, otherwise there is no result. (The by-position fit, which §15 uses, ignores constants that differ.)
3. For every position in order: a `<*>` token of the template gives one parameter, named `*`, whose value is the text of the message
   that the token stands for (the text from the start of its first character to the end of its last character, with every replacement
   inside it taken as it was written); the matches inside such a token give no parameter of their own. Any other token gives one
   parameter for each match that starts inside it, named by the rule and valued by the text that the rule matched.
4. A match whose replacement holds a delimiter belongs to the token in which it starts; a match with an empty replacement belongs to none.

The values are slices of the message, never recomputed text, so they hold every character of the log as it was written.

## 15. Values of the positions

`analyze(values=True)` counts the values that the records of the most frequent templates give to their variable positions
(ADR-016). The values cannot be taken while the tree is trained, because a position can become `<*>` later, so they are taken in the
pass of §9 that assigns every record to the finished tree: when a record is assigned to a template that is tracked, its parameters
are extracted by position (§14, the by-position fit: constants that differ are ignored, as in the assignment) and counted. The
counts of the templates are then those of that pass, and the values of a position add up to the records of the template.

- **Tracked templates:** the `value_templates` clusters (default 200) with the most records in the training pass, the ones with the same
  count in the order of their tokens. A template is tracked by its cluster, and the clusters of the same text are summed at the end.
- **Position:** the index of the token and the name of the parameter: `*`, or the name of a rule of the **default** masking rules. A
  parameter named by a rule of a mask set of the user is dropped before it is counted, so a value that such a set hides never reaches
  a report. A token with several matches of one rule gives them all to one position.
- **Counters:** a position counts exactly at most 1000 different values, each cut at its first 64 bytes; once the counters are full a value
  that is not among them is only added to `other` (the values that are among them keep counting). The report lists the 10 most frequent,
  by count (more first) and then by bytes, the number of counted values, whether the counters were full and `other`.
- **Numbers:** a value `-?digits(.digits)?` of at most 32 bytes is also a number. Numbers go into buckets that are one factor 1.05 wide
  (a number of 1e-9 or less in size is counted as zero, one above 1e15 goes to the last bucket); the limits of the buckets are
  `1.05^i` built by exactly rounded multiplications and divisions, so they are the same on every platform. The percentile `q` is
  the middle of the bucket of the number with the rank `floor(q * (count - 1))`, within about 2.4% of that number and between the smallest and
  the largest number; the report also has the count, the smallest, the largest and the mean.
- **Merging:** the parts of the input are merged in input order (§6): the counts of the buckets add up exactly in any order, so the
  numbers never depend on the chunks or the threads. The counters are exact while at most 1000 different values meet; above that
  the values that make it into the counters depend on the order of the input, which is the same for a fixed chunk size whatever the
  number of threads.

`ALGO_VERSION` does not change: the tree and the assignment are the same, the values are an addition to the result. The extension
contract version is 18.
