# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's *Report a vulnerability* feature on this repository, or by
e-mail to the maintainer listed in `pyproject.toml`. Do not open a public issue. Expect an acknowledgement within a week.

## Threat model

logfold reads log files that may contain attacker-controlled text and writes reports that people open.

- Inputs are untrusted. Memory use depends on the number of templates, not on the file size; `max_templates` caps it.
  `--values` and `--new-values` keep bounded counters as well (at most 1,000 different values per position for `--values`, and
  1,000,000 per position and 4,000,000 per run for `--new-values`; a position over its limit is reported as not compared).
- A saved state is untrusted too: it is read with a checksum and limits on the number of templates, nodes and bytes, and a state that is
  damaged, too large, from another algorithm version or mined with other masks is refused with a `StateError`.
- `docker:`, `kubectl:` and `journalctl:` sources run your own program only when you write a source, without a shell and with its input
  closed, looked up on `PATH` and never in the current folder, after the name was checked against a narrow pattern; the output is
  limited by a timeout and a size, and it lands in a temporary file that only you can read and that is removed afterwards.
- A `logfold.toml` is data of at most 64 KiB with no key that loads a plugin, runs a program or uses the network; a file that came with
  a cloned repository can only change how a run is done and what it reports, and the command says that it used one. A mask set file is
  data as well (at most 1 MiB and 256 rules, regular expressions of the linear-time engine).
- Regular expressions supplied by the user run in the Rust `regex` engine (linear time, no catastrophic backtracking).
- HTML reports escape every log-derived value, embed no network resources and carry a strict Content-Security-Policy.
- Plugins are Python code and run with your privileges once installed. `logfold plugins install` installs only names from
  a catalog, validates the catalog strictly (safe names and version constraints, printable text, size limits), shows
  the package and asks for confirmation. The catalog is bundled with logfold; it is downloaded (over HTTPS, never
  followed to plain HTTP) only for an explicit `--online` or `--catalog URL`, and `LOGFOLD_OFFLINE=1` forbids that.
  `analyze` and `diff` never use the network.
- Your own plugin folder is read from the user's config folder, `LOGFOLD_PLUGIN_PATH` and `--plugins-dir`, never from the
  current directory. On POSIX a folder or file that everybody can write to, or that belongs to another user, is skipped.
  `LOGFOLD_NO_USER_PLUGINS=1` switches the implicit folders off.
- The Markdown and CSV reporters neutralize log content: table cells cannot be broken out of, and CSV cells that a
  spreadsheet would read as a formula get a leading apostrophe.
- Example messages in reports are raw log lines and may contain secrets or personal data. Use `--examples masked` or
  `--examples none` before sharing a report. The mask sets (`--masks all`) hide tokens, keys, passwords and personal
  data in templates, saved states and masked examples (`secrets` and `pii` alone do not hide passwords or cards), but they
  find only what a rule can describe: they lower the risk and do not remove it.
