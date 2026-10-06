# Contributing

Thanks for helping. This page holds the rules for branches, commits, issues and pull requests.

## Setup

```
uv venv --python 3.13 .venv
uv pip install maturin
maturin develop --release --extras dev      # builds the Rust extension and installs dev tools
pytest
```

You need Rust 1.99 or newer (the minimum supported version, checked by its own CI job) and, on Windows, the MSVC build tools.

## Architecture rules (enforced in CI)

- Dependencies point inward only: `logfold-core` ← `logfold-io` ← `logfold-engine` ← `logfold-py` ← Python.
- `logfold-core` has no file I/O, threads, serialization formats, PyO3 or `unsafe`.
- The Python/Rust boundary is **one coarse call per use case**, never per line.
- Python layering is checked by `import-linter`; `logfold._core` is imported only from `engines/native.py`.
- The algorithm is a contract: [`docs/ALGORITHM.md`](docs/ALGORITHM.md). The Rust engine and the pure-Python reference
  engine must give identical results for the sequential strategy; change the spec, both engines and the equivalence
  tests in one pull request.
- Public contracts (Python API, CLI flags, exit codes, JSON schemas, `FormatSpec`) need a changelog entry.

## Code style

- Python: line length 120, Google-style docstrings on modules, classes and public functions, type hints everywhere
  (`mypy --strict`), `ruff` for lint and format.
- Rust: `rustfmt` (`max_width = 120`), `clippy -D warnings`, doc comments on public items.
- English for code, docstrings, comments, commits, issues and pull requests.
- No inline comments except for non-obvious workarounds, surprising deliberate choices and critical invariants.
- Log content is untrusted input: escape everything that goes into HTML; no secrets in code.

## Branches

- `main` is always green. No direct pushes; everything goes through a pull request with a squash merge.
- Branch name: `<type>/<issue>-<short-slug>`, for example `feat/12-new-format`, `fix/31-gz-boundary`.
  Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `chore`, `ci`.
- Keep branches short-lived and rebased on `main`.
- Releases are tags `vMAJOR.MINOR.PATCH` on `main` (SemVer; before 1.0 breaking changes only in a minor release).

## Commits

[Conventional Commits](https://www.conventionalcommits.org/): `type(scope): subject`.

- Types: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `build`, `ci`, `chore`, `revert`.
- Scopes: `core`, `io`, `engine`, `py`, `python`, `cli`, `formats`, `reporters`, `diff`, `bench`, `eval`, `ci`,
  `docs`, `deps`.
- Subject: imperative, lowercase, no trailing period, at most 72 characters. The body explains why, not what.
- Footer: `Closes #N` / `Refs #N`; breaking changes use `!` after the scope and a `BREAKING CHANGE:` footer.
- One logical change per commit; the tree builds and tests pass at every commit.

## Issues

Use the templates in `.github/ISSUE_TEMPLATE/`. Labels: `type:*`, `area:*`, `priority:p0|p1|p2`, `good first issue`
(see `.github/labels.yml`). A bug report needs a reproducer (command, a few sample lines with secrets removed,
`logfold info` output); a performance issue needs numbers and hardware.

## Pull requests and definition of done

The PR title follows the commit convention; fill in `.github/PULL_REQUEST_TEMPLATE.md` (What changed, Why, How to
verify, Risks and rollback). A change is done when all of these pass:

```
cargo fmt --all --check
cargo clippy --workspace --exclude logfold-py --all-targets -- -D warnings
cargo test --workspace --exclude logfold-py --exclude logfold-bench
ruff check . && ruff format --check . && mypy && lint-imports
pytest
```

Rust tests live in one package, `crates/logfold-tests` (`tests/<crate>.rs`, one module per topic), not inline in the crates; a test
needs only the public API of a crate. A source file has at most 500 lines (checked by `tests/test_source_size.py`).

New behavior has tests, user-visible changes are in `CHANGELOG.md`, and a change to an irreversible decision
(public contract, algorithm) is called out in the PR.
