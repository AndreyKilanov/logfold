# Migrating from Drain3

logfold mines templates with the same algorithm as [Drain3](https://github.com/logpai/Drain3) and has the same defaults
(`depth` 4, `sim_th` 0.4, `max_children` 100). With the same masks they give the same templates: on the 16 Loghub-2k datasets
the average grouping accuracy of Drain3 and of logfold in sequential mode is 0.7658. The masks are not the same by default,
see [Where the results differ](#where-the-results-differ). This page maps the Drain3 calls and settings to logfold, says where
the two differ, and lists what logfold does not have. It describes Drain3 0.9.11.

What changes for you: the mining is done by a Rust engine, the format of the log (the part before the message) is a
setting instead of code that strips it, and the state is a logfold state file.

## A loop, before and after

Drain3:

```python
from drain3 import TemplateMiner
from drain3.masking import MaskingInstruction
from drain3.template_miner_config import TemplateMinerConfig

config = TemplateMinerConfig()
config.drain_sim_th = 0.4
config.masking_instructions = [MaskingInstruction(r"\b\d+\.\d+\.\d+\.\d+\b", "IP")]
miner = TemplateMiner(config=config)

for line in lines:
    result = miner.add_log_message(line)
    if result["change_type"] == "cluster_created":
        print("new:", result["template_mined"])
```

logfold:

```python
import logfold

ip = logfold.MaskRule("ip", r"\b\d+\.\d+\.\d+\.\d+\b", "<IP>")
miner = logfold.Miner(sim_th=0.4, masks=(ip,))

miner.add_many(lines)  # one call for a batch of records
for template in miner.new_templates():  # created since the previous call
    print("new:", template)
```

Give `add_many` batches (hundreds to thousands of records) and ask for `new_templates()` after each one. Calling
`add_log_message(line)` for every line works too, but it crosses into the native engine once per line.

## Calls

| Drain3 | logfold |
|---|---|
| `TemplateMiner(config=..., persistence_handler=...)` | `Miner(**options)`; the state is a file: `Miner(load_state="model.json")` |
| `add_log_message(line)` | `add_many(records)`; `add_log_message(record)` is the same for one record and returns the number of records taken, not a dictionary |
| `result["template_mined"]` | `Miner.new_templates()` for new templates, `Miner.result().templates` for all of them |
| `result["cluster_size"]`, `len(miner.drain.clusters)` | `Template.count`, `len(result.templates)` of `Miner.result()` |
| `result["cluster_id"]` (an integer in creation order) | `Template.id`, the first 16 hex digits of `sha256(text)`; it changes when a template is generalized |
| `result["change_type"]` | none; a new template is in `new_templates()` |
| `miner.drain.clusters` | `Miner.result().templates`, most frequent first, with `count`, `level`, `first_seen`, `last_seen` and an `example` |
| `miner.match(line)` | [`miner.match(record, exact=True)`](api.md#miner), or `match_many(records, exact=True)` for a batch: a `TemplateMatch(id, text)` or `None`, nothing is learned. For a file: [`logfold.match(state, path, exact=True)`](api.md#match) or `logfold match STATE FILE --exact` |
| `miner.extract_parameters(template, line)` | [`miner.extract_parameters(template, line)`](api.md#extract_parameters) |
| `miner.get_parameter_list(template, line)` | `[p.value for p in miner.extract_parameters(template, line)]` |
| `FilePersistence` and `save_state` | `miner.save_state("model.json")`, or `logfold analyze --save-state` |

`extract_parameters` gives `Parameter(position, name, value)` instead of `ExtractedParameter(value, mask_name)`. The `name`
is the name of the masking rule (`ip`), not the `mask_with` text of Drain3 (`IP`), and `*` for a generalized position. Both
return nothing (`None`) for a line that does not fit the template. logfold has no `exact_matching=False`: the answer is
always the exact one.

## Settings

| `drain3.ini` / `TemplateMinerConfig` | logfold (`Miner(...)`, `MiningConfig`, `logfold.toml`) |
|---|---|
| `sim_th`, `depth`, `max_children` | the same names and defaults |
| `max_clusters` (unlimited by default) | `max_templates` (100000) with `on_full="evict"` for the least recently used eviction; see below |
| `extra_delimiters` (regular expressions) | `MiningConfig(delimiters=" \t\n\r_")`: ASCII characters that separate tokens, library only |
| `masking_instructions`, `MaskingInstruction(regex, "IP")` | `masks=(MaskRule("ip", regex, "<IP>"),)`, or `[[mining.masks]]` tables in [`logfold.toml`](config.md) |
| `mask_prefix`, `mask_suffix` | the whole token is the third argument of `MaskRule` (`"<IP>"`) |
| `parametrize_numeric_tokens` | always on |
| `snapshot_interval_minutes`, `snapshot_compress_state` | `logfold stream --save-every SECONDS`; in the library call `save_state` yourself; a state path that ends in `.gz` is compressed |
| `profiling_enabled` | `result.metrics` (wall times of the run) |
| `parameter_extraction_cache_capacity` | none; compiled masks are kept between calls |

## Where the results differ

- **Default masks.** Drain3 has no masks unless you add them; logfold masks UUIDs, timestamps, IP addresses, hex strings,
  paths and numbers by default (`<UUID>`, `<TS>`, `<IP>`, `<HEX>`, `<PATH>`, `<NUM>`). The same lines give `a <*>` in Drain3
  and `a <NUM>` in logfold. For the Drain3 behavior pass `masks=()` (`--no-masks`, `masks = "none"` in the file). Your own
  masks replace the default ones; extend them with `masks=(*logfold.ext.DEFAULT_MASKS, MaskRule(...))`.
- **Masking patterns.** They are regular expressions of a linear-time engine: look-ahead, look-behind and backreferences are
  not supported, and a rule that uses them stops with a `ConfigError` that names the rule. Rewrite the pattern without them
  or mask in two steps.
- **The prefix of a line.** With Drain3 you cut the timestamp and the level off the line in your own code. logfold does it
  with a format, and then gives `level`, `first_seen` and `last_seen` per template:
  `Miner(format="regex:^(?P<ts>\\S+) (?P<level>[A-Z]+) (?P<message>.*)$")`. The default is `plain` (the whole record is the
  message), and a stream cannot detect a format, so `auto` is refused. See [Formats](guide.md#formats).
- **Several lines.** A record may hold several lines (a stack trace): give `add_many` the whole record, or `add_lines` the
  physical lines and set `multiline`.
- **Identifiers.** A Drain3 `cluster_id` stays when a template changes. A logfold `Template.id` is a hash of the text, so
  it is the same in every run and on every machine, and a generalized template gets a new one. Store the text if you need
  to follow a template over time, or use [`diff`](guide.md#compare-two-runs), which matches templates between two runs.
- **Matching.** `TemplateMiner.match` asks for a perfect match (`sim_th` 1.0). `Miner.match` uses by default the similarity of
  mining: a record belongs to a template when at least the share `sim_th` of its tokens equals the constant tokens of the template
  (0.4), so it answers `None` less often. Pass `exact=True` (`--exact` for `logfold match`) for the perfect match of Drain3: every
  constant token of the template must equal the token of the record. Records that were pooled into the catch-all templates at
  the template limit have no template.
- **Memory limit.** When the number of templates reaches `max_templates`, further records that fit no template go to one
  catch-all template per token count (`<*> <*> <*>`), counts stay exact and `run.overflowed` is set. Drain3 with
  `max_clusters` evicts the least recently used cluster instead; pass `on_full="evict"` (`--on-full evict`) to do the same: a
  tenth of `max_templates` of the least recently used templates are dropped at a time, their counts join the catch-all
  template, and `run.evicted` says how many were dropped. A miner that evicts mines with one tree.
- **Threads.** A `Miner` takes one batch at a time, and the native call releases the GIL. For several sources give each its
  own `Miner`.

## Moving the state

A Drain3 state (the jsonpickle snapshot) is not read by logfold. Mine the logs again, once, and save the state:

```python
miner.save_state("model.json")  # "model.json.gz" is compressed; state_format="binary" is the compact format
miner = logfold.Miner(load_state="model.json", masks=(ip,), sim_th=0.4)
```

The state must be used with the masks and the parameters it was mined with; otherwise a `StateError` says so. It holds
templates and counts, never the lines. Kafka and Redis persistence do not exist: a state is a file, which you can store
wherever you keep files. See [State files](cli.md#state-files).

## What logfold does not have

| Drain3 | Instead |
|---|---|
| `full_search_strategy` of `match` | none: `match` always searches the tree and then every template of the same length |
| `parametrize_numeric_tokens=False` | none: a token with a digit always takes the wildcard branch of the tree, and `ALGORITHM.md` makes that part of the contract |
| Kafka and Redis persistence | a state file |
| `extra_delimiters` as regular expressions; delimiters in `drain3.ini` or a CLI flag | characters only, and only in `MiningConfig` |
| `change_type` for every line | `new_templates()` |
| `print_tree` | none |

## Speed

One machine, a 100 MB log of 1.27 million records, the same six masks, Drain3 as regular expressions
([`bench/docs/STREAM.md`](https://github.com/AndreyKilanov/logfold/blob/main/bench/docs/STREAM.md)):

| | Time | Speed |
|---|---:|---:|
| Drain3, `add_log_message` per line | 20.50 s | 5 MB/s |
| logfold, `add_log_message` per record | 3.12 s | 34 MB/s |
| logfold, `add_many` | 1.22 s | 86 MB/s |
| logfold, `analyze` on the file | 0.78 s | 134 MB/s |

A file is fastest with `analyze` (or `logfold analyze` in a shell), which also uses several cores for a big input.

## What else you get

`diff` of two runs, formats of common logs, reports (HTML, JSON, Markdown, JUnit), `logfold stream` for a pipe, `logfold match`
against a saved state and a settings file. Start with the [guide](guide.md).
