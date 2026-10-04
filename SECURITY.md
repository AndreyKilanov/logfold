# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's *Report a vulnerability* feature on this repository, or by
e-mail to the maintainer listed in `pyproject.toml`. Do not open a public issue. Expect an acknowledgement within a week.

## Threat model

logfold reads log files that may contain attacker-controlled text and writes reports that people open.

- Inputs are untrusted. Memory use depends on the number of templates, not on the file size; `max_templates` caps it.
- Regular expressions supplied by the user run in the Rust `regex` engine (linear time, no catastrophic backtracking).
  The pure-Python reference engine uses Python's `re`, which can backtrack: do not feed it untrusted patterns.
- HTML reports escape every log-derived value, embed no network resources and carry a strict Content-Security-Policy.
- Plugins are Python code and run with your privileges once installed. `logfold plugins install` installs only names from
  a catalog, validates the catalog strictly (safe names and version constraints, printable text, size limits), shows
  the package and asks for confirmation. The catalog is bundled with logfold; it is downloaded (over HTTPS, never
  followed to plain HTTP) only for an explicit `--online` or `--catalog URL`, and `LOGFOLD_OFFLINE=1` forbids that.
  `analyze` and `diff` never use the network.
- The Markdown and CSV reporters neutralize log content: table cells cannot be broken out of, and CSV cells that a
  spreadsheet would read as a formula get a leading apostrophe.
- Example messages in reports are raw log lines and may contain secrets or personal data. Use `--examples masked` or
  `--examples none` before sharing a report.
