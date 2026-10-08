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

### One step: the action

The repository has an action that does the whole recipe of this page: it installs logfold, analyzes the log, restores the
analysis of the last good run, compares, writes the summary of the run, optionally keeps an HTML report and fails the job on
new alerts.

```yaml
jobs:
  logs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - name: Run the tests, keep the log
        run: ./run-tests.sh > current.log 2>&1
      - uses: AndreyKilanov/logfold@v0.5.0
        with:
          log: current.log
```

Use the tag of a release (the action installs the logfold of the same version) and, on the default branch, run it after a
passing job. How it works:

- **The first run has no baseline**, so it only analyzes and writes the summary. A run on the default branch that passes is
  kept in the cache of the repository as the baseline (a small saved analysis, not the log). Runs of pull requests restore
  it, because they may read the caches of the default branch, and never write it.
  Until the default branch has run once there is nothing to restore, and the runs of pull requests only analyze.
- **A gate that found something fails the step** after the summary is written; `fail-on: none` only reports.
  With `fail-on: none` nothing fails, so every run of the default branch becomes the baseline, findings included.
- The cache is dropped when nobody reads it for seven days: a repository that runs on the default branch less often should
  give the baseline as a file (`baseline`).

| Input | Default | Meaning |
|---|---|---|
| `log` | required | The log of this run |
| `baseline` | cache | A log or a saved analysis (`.json`); empty means the baseline of the last good run |
| `fail-on` | `new-alerts` | `new-alerts`, `new` or `none` (see "Choosing the gate" below) |
| `level` | all | Keep this level and above, for example `ERROR` |
| `format` | `auto` | Log format |
| `examples` | `masked` | `masked`, `none` or `raw`; the summary and the cache are readable by everyone who can read the repository |
| `html-report` | none | Name of an artifact with the full HTML report |
| `save-baseline` | `auto` | `true`, `false`, or `auto` (the default branch only) |
| `baseline-key` | `default` | Name of the baseline in the cache (letters, digits, `_` and `.`); give each log of a repository its own |
| `version` | tag of the action | logfold version to install |
| `python-version` | `3.13` | Python to run it with (3.11 or newer) |

Outputs: `exit-code` (`0`, `2` for a gate, `1` for an error) and `status` (`first-run`, `ok` or `found`).

A saved analysis as the baseline is less exact than a baseline log: the two runs are mined apart and not re-counted
against one template tree, so a reworded message can show up as one new and one disappeared template (see the warning that
`diff` prints). The matcher pairs most of them. For a strict gate give a baseline log (`baseline: good/app.log`).

The inputs reach the shell as environment variables, never as part of a script, so a value cannot inject a command.

### By hand

GitHub shows the Markdown that steps append to `$GITHUB_STEP_SUMMARY` on the page of the run. Each step adds its own
section, so write with `--append`: without it a second logfold step would replace the first one's report.

```yaml
jobs:
  logs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7
      - uses: actions/setup-python@v7
        with:
          python-version: "3.13"
      - run: pip install "logfold[cli]"
      - name: Run the tests, keep the log
        run: ./run-tests.sh > current.log 2>&1
      - name: Compare with the last good run
        run: |
          logfold diff good/app.log current.log \
            --report github-summary --out "$GITHUB_STEP_SUMMARY" --append \
            --fail-on-new-alerts -q
```

`github-summary` is Markdown made for this file: a verdict line, the counts, the new templates with WARN and above first, the
changed and disappeared ones collapsed. It keeps under the 1 MiB that a step summary may hold and says when it listed fewer
templates, it shows templates and never example lines, and a log line in it cannot ping anyone or inject markup. (`--report
markdown` also works and writes plain tables.)

`--out` with `--report github-summary` or `markdown` (or a `.md` / `.txt` file) can be appended; `.html`, `.json`, `.csv`, `.xml` and
`.prom` cannot, because two documents in one file are not valid, and `--append` refuses them before it reads any log.

### Test results and metrics

A new WARN+ template as a failed test, for every tool that reads JUnit XML (a test report page, a flaky-test tracker):

```yaml
      - run: logfold diff good/app.log current.log --out logfold.xml --fail-on-new-alerts -q
      - uses: actions/upload-artifact@v7
        if: always()
        with:
          name: logfold-junit
          path: logfold.xml
```

`--out logfold.xml` writes JUnit: each new template is a test case, each new WARN+ template fails. A test report action reads the
file from the artifact or the workspace. In GitLab CI the same file is `artifacts: reports: junit: logfold.xml`, and the
merge request shows the new alarming templates as failed tests.

For a chat, `logfold diff ... --report chat-message` prints a short message (the headline and the top new templates in code
spans, within 3000 characters); put it in the body of your webhook call, logfold sends nothing. For a monitoring system,
`--out /var/lib/node_exporter/textfile/logfold.prom` writes gauges (records per level, new, disappeared and changed templates)
for the node exporter textfile collector.

The node exporter reads a `.prom` file whenever it is scraped, so it can read one that is half written, and then it reports
`node_textfile_scrape_error 1` for that scrape. Write the file beside the final one and move it into place; the collector reads
only files that end in `.prom`:

```
logfold diff good/app.log current.log --report prometheus --out /var/lib/node_exporter/textfile/.logfold.tmp -q
mv /var/lib/node_exporter/textfile/.logfold.tmp /var/lib/node_exporter/textfile/logfold.prom
```

### Checked with the real tools

The tests of the reporters parse the text themselves, so on 2026-10-08 the files of a diff (a baseline log and a run with
hostile template text: markup, a CDATA end marker, label metacharacters, control and astral characters, a 5000 character
line) were given to the programs that read them, in Docker. Command: `python bench/validate/reporters.py`.

| Report | Tool | Result |
|---|---|---|
| `prometheus` | `promtool check metrics` 3.15.0 | no problems, for a diff and for an analysis |
| `prometheus` | node exporter 1.12.1, textfile collector | `node_textfile_scrape_error 0`, 25 `logfold_` series |
| `junit` | `junit-10.xsd` of the Jenkins xunit plugin | valid, for a diff with new alerts and for a clean one |
| `junit` | Jenkins 2.541.3 with the JUnit plugin 1434 | 8 failed of 8 cases and the build `UNSTABLE`; a clean diff: the build `SUCCESS`, 1 passed |

Not checked: a GitLab server (the merge request widget reads the same file), other test report pages, and a Prometheus server
that scrapes the node exporter. The check found that on Windows the files had carriage returns before the line feeds, which
both Prometheus tools reject; reports are written with line feeds only since 0.5.0.

A full HTML report for people to download goes to a separate step, as an artifact:

```yaml
      - run: logfold diff good/app.log current.log --out diff.html --examples masked -q
        if: always()
      - uses: actions/upload-artifact@v7
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

### The template

`ci/gitlab/logfold.yml` defines a hidden job `.logfold`. It installs logfold, analyzes the log, compares it with the baseline
in the cache, writes `diff.html` and a JUnit file (a new WARN+ template is a failed test in the merge request) and fails
the job on the gate. A passing job on the default branch keeps its analysis as the next baseline.

```yaml
include:
  - remote: "https://raw.githubusercontent.com/AndreyKilanov/logfold/v0.5.0/ci/gitlab/logfold.yml"

logfold:
  extends: .logfold
  variables:
    LOGFOLD_LOG: current.log
  script:
    - ./run-tests.sh > current.log 2>&1
    - !reference [.logfold, script]
```

Variables: `LOGFOLD_LOG` (required), `LOGFOLD_FAIL_ON` (default `--fail-on-new-alerts`; set it to `--fail-on-new` or an empty
string), `LOGFOLD_EXAMPLES` (default `masked`), `LOGFOLD_VERSION` (default the latest release). The baseline is the file
`.logfold/baseline.json` in the cache `logfold-baseline`.

The template has been run in a `python` container with the script of the job. It has not been run on a GitLab server:
check the first pipeline and the artifact paths in your project.

### By hand

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
