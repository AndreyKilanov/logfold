# Sharing a log or a report safely

A report leaves the team: it goes to a vendor's support, a public issue, a chat or a ticket. Log lines carry things nobody
meant to publish: e-mail addresses, tokens, passwords in URLs, card numbers, names. logfold can keep many of them out of a
report; it cannot promise all of them. This page says which options do what, what stays, and how to check the file before it is
sent. The options are in the [command-line reference](cli.md#mask-sets), the rules of each set in `logfold masks show NAME`.

## The short recipe

```
logfold analyze app.log --masks all --examples none --out report.html
```

- `--masks all` hides the values that the shipped [mask sets](cli.md#mask-sets) can describe, **before** the log is mined, so
  they are in no template, no count and no saved state.
- `--examples none` leaves the example lines out. Without it the report keeps one raw example line per template, with
  everything in it: `--masks` does not touch the examples.

Both are needed. A run that selects mask sets and keeps raw examples says so on standard error.

## What each option does

| Option | Hides | Does not hide |
|---|---|---|
| `--masks secrets` | private keys, JWTs, API keys with a known prefix (AWS, GitHub, GitLab, Slack, Stripe, Google, npm, SendGrid, `sk-`) | a password without a prefix or a label |
| `--masks pii` | e-mail addresses, international phone numbers | names, addresses, phone numbers without `+` |
| `--masks credentials` | `Authorization` headers, `Bearer` tokens, `password=`, `token=`, `api_key=` pairs, passwords in URLs | a secret that is not labelled |
| `--masks payment` | card numbers (the Luhn check) and IBANs (the mod-97 check) | any other account number |
| `--masks all` | the four sets above | everything in the right-hand cells |
| default masks (always on) | numbers, IPs, UUIDs, timestamps, paths, hex values | words |
| `--examples masked` | applies the same masks to the example lines | |
| `--examples none` | drops the example lines (`--values` then keeps its counts and numbers and leaves out the list of values) | |

`secrets` and `pii` are cheap (a few percent of the run time) and **do not hide passwords, cards or IBANs**; `credentials` and
`payment` read every byte and cost more (see [what they cost](cli.md#mask-sets)). `--masks all` costs about 11 to 24%.

## What stays

Take a log with these lines:

```
2026-10-15 10:00:03 ERROR request failed password=hunter2secret url=https://api.x.io/v1?token=abcd1234efgh5678
2026-10-15 10:00:05 INFO key AKIAIOSFODNN7EXAMPLE used by carol
2026-10-15 10:00:06 INFO payment card 4111 1111 1111 1111 charged for dave
```

With `--masks all --examples none` the templates are:

```
request failed <SECRET> url=https:/<PATH>?<SECRET>
key <KEY> used by carol
payment card <CARD> charged for dave
```

The password, the token, the key and the card are gone from the report, and `carol` and `dave` are not. No set knows what a
person's name is. The same holds for host names, user names, order numbers that are words, and the text of the messages
themselves. A template is the message with its variable parts replaced, so the constant words of every line stay.

Two more things are in the report. The run name is the **base name** of the input file (`app.log`, not its folder), and the
times of the first and last record of each template are kept.

## Your own identifiers

A rule is a regular expression of a linear-time engine and a token. Put the identifiers of your system in a file:

```json
{
  "name": "people",
  "rules": [
    {"name": "customer", "pattern": "customer=[a-z]+", "token": "<CUSTOMER>"}
  ]
}
```

```
logfold analyze orders.log --masks all --masks-file people.json --examples none --out report.html
```

`order paid customer=carol` becomes `order paid <CUSTOMER>`. A rule runs fast when its matches share a literal (`customer=`,
`ORD-`) and slowly when they do not (`[0-9]{16}`). The [schema](schema/mask-set.schema.json) lists the fields, and
`logfold masks show payment` shows how the shipped rules are written. A plugin can ship a set for a whole team: see
[plugins](plugins.md#mask-sets).

## Check the file before it leaves

Search the file for values you know are in the log:

```
grep -c -e hunter2secret -e alice@example.com report.json report.html
```

```
Select-String -Path report.json,report.html -Pattern 'hunter2secret','alice@example.com'
```

A count of `0` for each is what you want. Then read the template table once as a stranger would: it is short. The
[JSON report](schema/analysis-v1.schema.json) and the HTML one hold the same templates.

## Reports and saved states

- **An HTML report** is one file with no network access and a strict Content-Security-Policy; every log-derived value is escaped,
  so opening a report of a hostile log does not run anything.
- **A saved state** (`--save-state`) holds templates and counts and never an example line, but its templates are made of the
  words of your log: treat it like a report.
- **Saved results for `diff`** keep their examples as they were saved. `--examples masked` is refused at `diff`, so choose
  `masked` or `none` when you analyze.
- **A report on a bug.** Open the [format form](https://github.com/AndreyKilanov/logfold/issues/new?template=format_problem.yml) or the
  bug report with about 20 lines whose secrets you removed by hand. logfold does not rewrite a log file, and a public issue is
  public.

## What this does not do

The mask sets lower the risk and do not remove it. A rule finds what it can describe (a prefix, a label, a checksum), not a
password in the middle of a sentence, and it may mask something that only looks like a secret (the word `token` followed by
a long value). `bench/docs/MASK_SETS.md` lists what the sets changed on 16 public logs. If the log is sensitive, the safest report is
the one that was read by a person before it was sent.
