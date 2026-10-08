# State files: size and speed

A state file holds a saved miner: the parameters, the shape of the tree, the templates and the counts of earlier runs
(`logfold-io`, module `state`). It comes in two forms with the same content: JSON (readable, the default) and binary
(compact). This page measures both before the feature ships, on 10 thousand, 100 thousand and a million templates (the
default limit), to see how much each costs and whether the readable form is fast enough.

## Method

`cargo test --release -p logfold-tests --test io_state -- --ignored --nocapture measure_state_files` builds a valid
snapshot directly (no mining): templates of six tokens in 100 leaves, each with its history of counts and times. For each
size and form it times writing the bytes, reading them back with all checks (the checksum, the limits, the parse), and
rebuilding the miner from the snapshot with all its checks. One run each, release build, Windows 11, 8 cores / 16 threads,
warm cache; the 0.5.0 development code.

## Results

| templates | form | bytes | bytes per template | write | read | rebuild the miner |
|---:|---|---:|---:|---:|---:|---:|
| 10,000 | JSON | 1,154,039 | 115 | 11 ms | 11 ms | 6 ms |
| 10,000 | binary | 584,559 | 58 | 3 ms | 5 ms | 6 ms |
| 100,000 | JSON | 11,613,825 | 116 | 107 ms | 116 ms | 69 ms |
| 100,000 | binary | 5,924,261 | 59 | 31 ms | 60 ms | 72 ms |
| 1,000,000 | JSON | 117,111,707 | 117 | 1,102 ms | 1,202 ms | 974 ms |
| 1,000,000 | binary | 59,384,141 | 59 | 329 ms | 581 ms | 959 ms |

## Reading the numbers

- Both forms grow linearly (ten times the templates, ten times the time and the bytes).
- Binary is half the size and 2 to 3 times faster to write and about 2 times faster to read. Rebuilding the miner costs the
  same for both.
- The tokens of this input are short (about four bytes); real templates are longer, so JSON is closer to 170 to 750 bytes per
  template (measured on real logs, see the design notes) and binary to a half of it.
- **The condition of the design is met:** 100 thousand templates read and rebuild in about 0.2 s in JSON (the limit for
  changing the default was one second). JSON stays the default; binary is for states of hundreds of thousands of templates,
  where it saves 60 MB and about 0.6 s per million.
