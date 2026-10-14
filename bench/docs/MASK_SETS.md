# Mask sets: speed and false positives

`--masks secrets,pii` runs the rules of the built-in sets in front of the default masks (a first layer matched by the
regex engine, then the hand-written scanner of the default masks over the text that is left). This page measures what that
costs on logs that hold no secrets, why the sets are split the way they are, and what they do to ordinary logs.

## Speed

`python bench/speed.py masks FILE --repeat 7` runs `logfold analyze FILE -f plain --engine native --strategy sequential
--examples none` in a separate process for every variant (the method of `bench/speed.py`: wall time, median, warm page
cache) and prints the overhead over the default masks. The "30 own rules" variant adds a set file with 30 simple rules of
the kind a user writes. One machine (Windows 11, i7-10700K, 8 cores / 16 threads, Python 3.13), the 0.5.0 development code.

Whole run, overhead over the default masks:

| Input | Default masks | `secrets` | `pii` | `secrets` + `pii` | `credentials` | `payment` | `all` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `app_10mb.log` | 0.39 s | +2% | 0% | +1% | +2% | +2% | +7% |
| `app_100mb.log` | 0.84 s | +7% | +1% | +10% | +19% | +20% | +20% |
| `nginx_100mb.log` | 1.00 s | +3% | +2% | +4% | +15% | +12% | +11% |
| `loghub_100mb.log` | 1.25 s | +9% | +6% | +11% | +13% | +13% | +17% |

The runs are noisy by several points (the default masks of `nginx` took 0.92 s in another run, `all` on `app` +24%). Memory does not change (a few
MB). The 10 MB runs are mostly the start of the interpreter.

**`secrets` + `pii` cost 4 to 12% on logs without secrets (a second run: 7 to 12%), under the 15% that was wanted. The other
two sets, and `all`, cost 11 to 24%.** A set of your own with rules that have no literal (a number of 16 digits) costs like them; so do more than
64 literals in all.

### Why the sets are split by cost

A throwaway Rust loop (not kept in the repository) over the first 41 MB of `app_100mb.log` (506,465 lines), the masker alone,
best of 5, with all the rules as one regex:

| Masker | Time | Per line |
|---|---:|---:|
| default masks | 61 ms | 121 ns |
| + all rules of `secrets` and `pii` | 122 ms | 242 ns |
| + `card` alone | 124 ms | 244 ns |
| + `iban` alone | 123 ms | 242 ns |
| + `credential_pair` or `auth_header` alone | 106 ms | 208 ns |
| + `email`, `phone` or `url_password` alone | 72 to 75 ms | 141 to 148 ns |
| + `jwt` or one key rule alone | 78 to 80 ms | 155 to 158 ns |

A rule that has a literal the engine can search for (`@`, `+`, `://`, `eyJ`, `AKIA`) costs 10 to 20 ms. A rule that can start
anywhere (a digit, a capital letter, a word in any case) makes the lazy DFA read every byte, about 1.4 ns, and that is the
floor: even `[A-Z]{2}\d{2}` alone costs 60 ms. The cost of the combined set is the cost of that one pass, whatever the number of
rules (30 more rules add nothing measurable). So one rule of the second kind makes the whole first layer dear, which is why
`credentials` (words in any case) and `payment` (numbers) are sets of their own.

What did not help the dear rules (measured, same data): a bigger DFA cache, a fully compiled DFA (1.45 ns per byte, a 15 s
build), keeping the search cache in the scratch buffer (3%), simpler card patterns (slower), searching several lines in
lockstep through the lazy DFA (no gain), joining lines into one text (the per-call cost is only 15%), and a gate of
cheap checks in front of the card, IBAN and word rules (the gate alone cost more than the regex, and it passed 66% of the
lines of `loghub`).

### The gate of the cheap sets

When every rule of the first layer has literals that each of its matches must contain, the first layer first looks for them
(the literals a match starts with, or a literal inside such as `@` or `://`, taken from the pattern) and runs the regex
engine only on text that has one. The matches are those of the regex (a property test compares them on random lines, and a
Python test fails if a built-in cheap set loses its gate). The gate itself is an Aho-Corasick automaton with its SIMD
prefilter (0.46 ns per byte over 30 key prefixes) and `memchr` for single bytes such as `@`:

| Gate over the 30 key prefixes of `secrets` | ns per byte |
|---|---:|
| `AhoCorasick::new` (standard match kind) | 1.34 |
| leftmost match kind (Teddy prefilter) | 0.46 |
| + the nine `+1` ... `+9` literals of `phone` | 0.75 |
| + `@` as a literal of the automaton (the prefilter is lost) | 1.34 |
| `memchr` for `@` and `+` first, the automaton for the rest | 0.55 |

Teddy takes at most 64 patterns and no one-byte pattern, so a gate has at most 64 literals and at most three single bytes.
A literal is useful only when ordinary text rarely has it: three bytes or more, two that are not both letters or digits, or
one of `@ + # $ % ^ & ~`; the digits that a number starts with would pass nearly every line.

## False positives and grouping accuracy

`python eval/mask_sets.py` mines the message column of the 16 Loghub-2k samples (2,000 messages each, no known secrets)
with the default masks and with `--masks all`, and scores grouping accuracy as `eval/quality.py` does.

| | Default masks | `all` |
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

* `secrets` and `pii` do not hide passwords (`password=...`, `Authorization: Bearer ...`), card numbers or IBANs: those are
  `credentials` and `payment`, and `--masks all` takes everything.
* A number of 14 to 16 digits that starts like a card and passes the Luhn check is masked as `<CARD>` (about 1 in 10 of
  such random ids).
* The word `token`, `secret`, `api_key`, `access_key` or `private_key` followed by `:` or `=` and a value of 8 or more
  characters is masked, whatever the value means.
* A key rule that needs a prefix finds only keys that have one (`AKIA`, `ghp_`, `xoxb-`, `sk_live_`, ...); a random
  password without a label is not found. The sets lower the risk, they do not remove it.
