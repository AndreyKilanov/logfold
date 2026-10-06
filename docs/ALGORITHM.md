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
mode skips lines until a record start. A chunk keeps consuming lines after `e` (continuation lines, blank lines and, before the first record of a file, unparsed lines) until the next line that starts a record; that line belongs to the next chunk. Compressed files are a
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
*changed* or *unchanged*. The native comparison (`logfold-core`, `compare`) and the pure-Python one
(`logfold.comparison.classify`) must return **identical** entries, in the same order, with identical floats (the same
IEEE double operations in the same order). It does not change mined templates or counts, so it does not affect
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

`github-summary`, `junit`, `chat-message` and `prometheus` turn a result into text. The Rust core
(`logfold-core`, `report`) and the pure-Python reporters (`logfold.plugins.reporters_ci`, `reporters_feeds`, the reference)
must write **byte-identical** text for the same result and options. They do not change mined templates or counts, so they
do not affect `ALGO_VERSION`. The extension takes the columns of a result in one call, `render_report(report, data, options)`
(contract version 7); without the extension, or for a text it cannot take (a lone surrogate), the Python reporter renders.
The Python reporter also renders when only a small part of a large result is listed, because building the columns passes
over every template (`report_data.MIN_LISTED`, `LISTED_FRACTION`); the choice never changes the text.

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
