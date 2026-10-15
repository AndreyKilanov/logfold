# Finding what changed in an incident

A service broke. You have a log from before and a log from after, or one log that spans the failure, and you want to know
what is new, what is gone and what moved, without reading a million lines. This page is the order of commands that gets
there. The options are in the [command-line reference](cli.md#logfold-diff), the ideas behind them in the
[guide](guide.md#compare-two-runs).

## 1. Check that the log is read

```
logfold inspect after.log
```

```
format     app (auto-detected, 100% of the sample); multiline off
sample     600 lines: 600 records, 0 unparsed
time       2026-10-15 12:00:00 -> 2026-10-15 13:58:00
levels     ERROR 180 WARN 60 INFO 360
```

The levels and the time range are what the rest of the page uses. When the format is `plain`, there is no level and no time:
name the right format with `-f` (`logfold formats` lists them) before going on. If `-f auto` fails, pass `-f plain`, or
[tell logfold what a line looks like](guide.md#formats).

## 2. Compare the two runs

```
logfold diff before.log after.log --out incident.html
```

```
before.log -> after.log: 364 -> 600 records, 1 new (1 WARN+), 0 disappeared, 1 changed, 2 unchanged, native engine, 0.01s

New templates (1)
    before       after    change  level  template
         0         180       new  ERROR  db connection timeout after <*> <*>

Changed templates (1)
    before       after    change       p  level  template
         4          60     x9.10  <0.001  WARN   retry <NUM> for order <NUM>

Disappeared templates (0)
  none
```

- **New** is a message that exists after and not before: the first place to look. Its level tells how loud it is.
- **Changed** is a message that exists in both and whose share moved by at least a factor of 2 and significantly (`p`). The
  shares are of each run's records, so a run twice as long is not a reason.
- **Disappeared** is a message that stopped. A missing log line is also a symptom (a job that no longer runs).

`incident.html` holds the same tables and can be opened offline or attached to the ticket; see
[sharing a log safely](share-a-log.md) before it leaves the team.

## 3. One log across the failure

When there is no clean "before" file, cut the log at the time it started:

```
logfold diff app.log --split-at 2026-10-15T12:00 --since 2026-10-15T11:00 --until 2026-10-15T13:00
```

The hour before `12:00` is the first run and the hour after it the second one. It needs a format with a time. Records
without a time cannot be placed and are counted apart (`run.untimed`).

## 4. Keep only what matters

```
logfold diff before.log after.log --level ERROR           # new, disappeared and changed templates at ERROR or above
logfold diff before.log after.log --min-count 20          # hide changes of fewer than 20 records
```

`--level` filters the lists, the reports and the exit code together. The template level is the most severe one among its
records.

## 5. Look inside a template

A template says that a part varies. To see how it varied, count the values:

```
logfold analyze after.log --level ERROR --values --top 1
```

```
     count    share  level  template
       180   30.00%  ERROR  db connection timeout after <*> <*>
                          [4] * (180 values, 2 distinct): 30000ms x141, 45000ms x39
                          [5] * (180 values, 3 distinct): host=db3 x74, host=db1 x56, host=db2 x50
```

Here it is every database host and not one of them. [`--values`](cli.md#values-of-the-parameters) takes a second pass, a few times
slower than the plain run. To read the values of one message, use [`logfold params`](cli.md#logfold-params).

A template that is the same in both runs can still change in its values. To see which numbers or names only one run has, add `--new-values` to the
`diff` of step 2: [new and gone values](cli.md#new-and-gone-values).

## 6. Read the log from where it is

With `docker`, `kubectl` or `journalctl` installed, name the source instead of dumping a file:

```
logfold diff docker:web-old docker:web-new
logfold analyze kubectl:prod/web-7d9 --source-since 1h --source-previous
```

`--source-previous` reads the container that crashed, before the restart. The programs run read-only, with a timeout and a size
limit, and nothing is kept after the command ends: see [sources](cli.md#sources-reading-a-log-from-docker-kubectl-or-journalctl).

## 7. Reduce the noise

A template that is missing from one good run may still be normal. Give `diff` more good runs, and it reports as new only what
none of them has:

```
logfold diff good1.log after.log --baseline good2.log --baseline good3.log
```

Three to five recent good runs are enough. A message that occurs in some of them but not in all is called unstable and is
reported as nothing. See [several baselines](guide.md#compare-with-several-baselines).

## What the result does not tell

- It shows what differs, not why. A new `ERROR` template is where to start reading the lines around it, with the times that
  the report gives for its first and last record.
- A template that was reworded between the two runs may show as one new and one disappeared message. The matcher
  (`jaccard` by default) pairs most of them as `changed`; [choosing one](guide.md#choosing-a-matcher) says when to try another.
- The two runs should be alike: the same service, the same kind of day. A Monday log against a Sunday log shows the
  difference between days.

## Keep it for later

```
logfold analyze after.log --out after.json
logfold diff before.json after.json
```

A saved result is small and compares in an instant, even when the logs are gone. Analyze both with the same options: a note
warns when the settings differ. To fail a pipeline on the same findings, see [logfold in CI](ci.md).
