# Mask sets: speed and false positives

`--masks secrets,pii` runs the rules of the built-in sets in front of the default masks (a first layer matched by the
regex engine, then the hand-written scanner of the default masks over the text that is left). This page measures what that
costs on logs that hold no secrets, and what the sets do to ordinary logs.

## Speed

`python bench/speed.py masks FILE --repeat 5` runs `logfold analyze FILE -f plain --engine native --strategy sequential
--examples none` in a separate process for every variant (the method of `bench/speed.py`: wall time, median of 5, warm page
cache) and prints the overhead over the default masks. The "30 own rules" variant adds a set file with 30 simple rules of
the kind a user writes. One machine (Windows 11, i7-10700K, 8 cores / 16 threads, Python 3.13), the 0.5.0 development code.

Whole run, overhead over the default masks:

| Input | Default masks | `secrets` | `pii` | `secrets` + `pii` | + 30 own rules |
|---|---:|---:|---:|---:|---:|
| `app_10mb.log` | 0.40 s | +2% | +8% | +7% | +7% |
| `app_100mb.log` | 0.86 s | +20% | +19% | +19% | +23% |
| `nginx_100mb.log` | 0.92 s | +18% | +18% | +20% | +24% |
| `loghub_100mb.log` | 1.29 s | +15% | +13% | +17% | +22% |

Memory does not change (a few MB). The 10 MB runs are mostly the start of the interpreter.

**The goal was at most 15% for `secrets` + `pii` on logs without secrets. It is not met on 100 MB logs (17 to 20%).**

### Where the time goes

A throwaway Rust loop (not kept in the repository) over the first 41 MB of `app_100mb.log` (506,465 lines), the masker alone, best of 5:

| Masker | Time | Per line |
|---|---:|---:|
| default masks | 61 ms | 121 ns |
| + `secrets` | 122 ms | 242 ns |
| + `pii` | 123 ms | 243 ns |
| + `secrets` + `pii` | 124 ms | 245 ns |
| + `card` alone | 124 ms | 244 ns |
| + `iban` alone | 123 ms | 242 ns |
| + `credential_pair` or `auth_header` alone | 106 ms | 208 ns |
| + `email`, `phone`, `url_password` alone | 72 to 75 ms | 141 to 148 ns |
| + `jwt` or one key rule (`aws_key`) alone | 78 to 80 ms | 155 to 158 ns |

A rule that has a literal the engine can search for with `memchr` or a literal prefilter (`@`, `+`, `://`, `eyJ`, `AKIA`)
costs 10 to 20 ms. A rule that can start anywhere (a digit, a capital letter, a word in any case) makes the lazy DFA read
every byte of every line, about 1.4 ns per byte, and that is the floor: even `[A-Z]{2}\d{2}` alone costs 60 ms. The cost
of the combined set is the cost of that one pass, whatever the number of rules (30 more rules add nothing measurable). Tried
and dropped: a bigger DFA cache, a fully compiled DFA, keeping the search cache in the scratch buffer (3%), simpler card
patterns (slower). The hand-written scanner of the default masks, which skips most bytes, is itself 1.4 ns per byte of the
text on these logs, so the pass of the first layer roughly doubles the masking stage, which is about a sixth of a run.

Getting under 15% needs the rules of the sets to share the pass of the default scanner (one hand-written scanner for the
built-in sets, tested against the regex engine as the default scanner is), or a line prefilter that rejects most lines
without reading them. Neither is built; the cost is a follow-up (issue linked from the pull request).

## False positives and grouping accuracy

`python eval/mask_sets.py` mines the message column of the 16 Loghub-2k samples (2,000 messages each, no known secrets)
with the default masks and with `secrets` + `pii`, and scores grouping accuracy as `eval/quality.py` does.

| | Default masks | `secrets` + `pii` |
|---|---:|---:|
| Average grouping accuracy | 0.7658 | 0.7658 |
| Datasets where it differs | | 0 of 16 |
| Messages changed | | 13 of 32,000 |

The changed messages:

| Dataset | Messages | What matched |
|---|---:|---|
| Android | 6 | `token = AppWindowToken{...}` and `token=Token{...}` taken for a token: the word `token` followed by a value of 8 or more characters that does not start with a bracket |
| Mac | 4 | e-mail addresses written as `user%40host.com@server` (a real address in a URL) and `token: com.apple...` |
| Linux | 1 | a build user's e-mail address (a real address) |
| HDFS | 1 | a 16 digit block id that happens to pass the Luhn check |

Block ids of 18 and 19 digits matched the card rule in the first version (16 messages) because 10% of random numbers pass
the Luhn check; the card rule now takes the real lengths of the card families only (13 and 17 to 19 digits left out).
`token`, `secret` and the other key words need a value of 8 characters, the password words 3.

## Limits that follow

* A number of 14 to 16 digits that starts like a card and passes the Luhn check is masked as `<CARD>` (about 1 in 10 of
  such random ids).
* The word `token`, `secret`, `api_key`, `access_key` or `private_key` followed by `:` or `=` and a value of 8 or more
  characters is masked, whatever the value means.
* A key rule that needs a prefix finds only keys that have one (`AKIA`, `ghp_`, `xoxb-`, `sk_live_`, ...); a random
  password without a label is not found. The sets lower the risk, they do not remove it.
