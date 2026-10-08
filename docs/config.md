# Settings file `logfold.toml`

Put the settings that you repeat in every command into a `logfold.toml` file at the root of your repository. The commands
`analyze`, `match`, `diff` and `inspect` read it, and so do the library functions when you pass `config=`.

```toml
format = "app"                  # the default of --format

[mining]
sim_th = 0.5
masks = "default"               # "default", "none", or your own [[mining.masks]] tables

[execution]
strategy = "auto"
chunk_mb = 64

[output]
top = 30
examples = "masked"

[diff]
matcher = "jaccard-idf"
significance = 0.01
fail_on_new_alerts = true       # exit code 2 when a new WARN/ERROR/FATAL template appears
```

Every key is optional. A [JSON schema](schema/config.schema.json) describes the file.

## Which setting wins

A flag on the command line beats the file, and the file beats the built-in default. In the library, an argument of the call
beats the `Settings` that you pass as `config=`. There are no environment variables for single settings.

## Where the file is found

1. `logfold --config FILE ...` (or the variable `LOGFOLD_CONFIG`): that file, and an error if it cannot be read.
2. Otherwise the first `logfold.toml` in the current folder or in a folder above it, up to the first folder that has a `.git`
   entry (that folder is searched too) or to the root of the file system. The home folder and system folders are not searched.
3. `logfold --no-config ...` reads no file at all.

A command that uses a file says so on standard error (`config: /path/logfold.toml`); `--quiet` keeps that line out.

## Keys

| Section | Key | Meaning |
|---|---|---|
| (top) | `format`, `multiline` | the same as `--format` and `--multiline` |
| `[mining]` | `depth`, `sim_th`, `max_children`, `max_templates` | the parameters of the miner (see the [CLI reference](cli.md)) |
| `[mining]` | `masks` | `"default"`, `"none"` (like `--no-masks`) or a list of tables `[[mining.masks]]` with `name`, `pattern`, `token` and an optional `ascii` |
| `[execution]` | `strategy`, `threads`, `chunk_mb`, `warm_start` | the same as the flags of the same name; `threads` is at most 1024 in a file |
| `[output]` | `top`, `examples`, `report`, `level`, `only_alerts` | what is printed and written |
| `[analyze]` | `min_count` | `--min-count` of `analyze` and `match` |
| `[diff]` | `threshold_ratio`, `min_count`, `min_new_count`, `significance`, `matcher`, `recount` | the comparison, as the flags of `diff` |
| `[diff]` | `fail_on_new`, `fail_on_new_alerts` | the exit code 2 of `diff` |

An unknown key or section, a value of the wrong type or a value out of range stops the command with an error that names the
file and the key, and suggests the closest known name (`unknown key 'depht' in [mining]`, `did you mean 'depth'?`).

## Safe to keep in a repository

The file is data. It has no key that loads a plugin, runs a program or uses the network, so a file that came with a cloned
repository can only change how a run is done and what it reports, which is its purpose, and the command tells you that it
uses one. It must be UTF-8 and at most 64 KiB. A masking pattern is a regular expression of the linear-time engine, as
everywhere in logfold.

## Settings and saved states

A state file records a fingerprint of the masks and parameters it was mined with. Use the same `logfold.toml` for
`analyze --save-state` and for `match` or `--load-state`: if the settings differ, the command stops with an error that says
so (see [State files](cli.md#state-files)).

## In the library

```python
import logfold

settings = logfold.load_config()  # the file found as above, or the defaults
result = logfold.analyze("app.log", config=settings)
result = logfold.analyze("app.log", config=settings, sim_th=0.6)  # the argument wins
```

`load_config(path=None)` returns a `Settings`. It gives `analyze`, `match` and `diff` the format, `multiline`, the mining and
execution configuration and, for `diff`, the comparison configuration, wherever the call does not name them.
