# logfold in CI

How to use `logfold diff` as a check in a pipeline: compare the logs of a run with a known good one, show the result in
the job summary and fail the job when something new and alarming appears.

## What a pipeline needs

- `pip install "logfold[cli]"`: prebuilt packages for Linux, macOS and Windows, no Rust compiler.
- **Exit codes:** `0` nothing requested was found, `1` an error (unreadable file, bad option), `2` a `--fail-on-new` or
  `--fail-on-new-alerts` condition was found. A pipeline can tell a finding from a broken step by the code.
- **The report is written before the gate fails**, so a failed job still has its report.
- `-q` keeps the progress and the "wrote ..." lines out of the job log.
- **Examples in a report are raw lines by default.** A job summary is visible to everyone who can read the repository,
  and a log may hold names, addresses or tokens. Use `--examples masked` (values replaced) or `--examples none` for
  anything that is shared.

## GitHub Actions

GitHub shows the Markdown that steps append to `$GITHUB_STEP_SUMMARY` on the page of the run. Each step adds its own
section, so write with `--append`: without it a second logfold step would replace the first one's report.

```yaml
jobs:
  logs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - run: pip install "logfold[cli]"
      - name: Run the tests, keep the log
        run: ./run-tests.sh > current.log 2>&1
      - name: Compare with the last good run
        run: |
          logfold diff good/app.log current.log \
            --report markdown --out "$GITHUB_STEP_SUMMARY" --append \
            --examples masked --fail-on-new-alerts -q
```

`--out` with `--report markdown` (or a `.md` / `.txt` file) can be appended; `.html`, `.json` and `.csv` cannot, because
two documents in one file are not valid, and `--append` refuses them before it reads any log.

A full HTML report for people to download goes to a separate step, as an artifact:

```yaml
      - run: logfold diff good/app.log current.log --out diff.html --examples masked -q
        if: always()
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: logfold-diff
          path: diff.html
```

Check the current major versions of the `actions/*` steps when you copy this.

### Where the good run comes from

`diff` needs a baseline. Three ways, from the simplest:

- **Commit it** next to the tests (`good/app.log`), when the log is small and stable.
- **Keep the last good analysis**, which is much smaller than the log. Save it on the main branch and restore it in the
  other jobs (a cache or an artifact), then compare saved results without reading the baseline log again:

  ```
  logfold analyze current.log --out current.json --examples masked -q
  logfold diff baseline.json current.json --report markdown --out "$GITHUB_STEP_SUMMARY" --append --fail-on-new-alerts -q
  ```

  On the main branch, `logfold analyze app.log --out baseline.json --examples masked` after a green run makes the next
  baseline. A `.json` file written with `--out` always holds every template, so it can be compared. The examples stay
  as they were saved, so choose `--examples` when you analyze, not in `diff`.
- **Use several good runs.** One run misses rare messages, which then look new in the next run. Pass the last three to
  five good logs and a template counts as new only if none of them has it:

  ```
  logfold diff good1.log current.log --baseline good2.log --baseline good3.log --fail-on-new-alerts
  ```

  This works for logs, not for saved results (see [`diff` with several baselines](guide.md#compare-with-several-baselines)).

## GitLab CI

GitLab has no summary file, so keep the HTML report as a job artifact. `when: always` keeps it when the gate fails.

```yaml
logfold:
  image: python:3.13
  script:
    - pip install "logfold[cli]"
    - ./run-tests.sh > current.log 2>&1
    - logfold diff good/app.log current.log --out diff.html --examples masked --fail-on-new-alerts -q
  artifacts:
    when: always
    paths:
      - diff.html
```

To show findings without failing the pipeline, let exit code 2 (and only it) pass:

```yaml
  allow_failure:
    exit_codes: 2
```

## Choosing the gate

| Option | Fails the job when |
|---|---|
| `--fail-on-new` | any template is new (not in the baseline) |
| `--fail-on-new-alerts` | a new template has level WARN, ERROR or FATAL |
| `--fail-on-new --level ERROR` | a new template has level ERROR or FATAL (`--level` also hides lower levels from the report; a format without levels is an error) |

The gates look at **new** templates only. A reworded message that the matcher pairs with an old one counts as changed,
not new (`--matcher exact` makes the gate strict). A format without levels (for example `plain`, nginx or apache) has no
alerts, so `--fail-on-new-alerts` never fires on it: use `--fail-on-new`.
