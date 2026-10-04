# Contributing

Thanks for helping. The rules for branches, commits, issues and pull requests are in [`CLAUDE.md`](CLAUDE.md); this
page is the short version.

## Setup

```
uv venv --python 3.13 .venv
uv pip install maturin
maturin develop --release --extras dev      # builds the Rust extension and installs dev tools
pytest
```

You need a Rust toolchain (stable) and, on Windows, the MSVC build tools.

## Before you open a pull request

```
cargo fmt --all --check
cargo clippy --workspace --exclude logfold-py --all-targets -- -D warnings
cargo test --workspace --exclude logfold-py --exclude logfold-bench
ruff check . && ruff format --check . && mypy && lint-imports
pytest
```

- Branch: `<type>/<issue>-<slug>`, for example `feat/12-new-format`.
- Commits: [Conventional Commits](https://www.conventionalcommits.org/) (`feat(core): ...`).
- The algorithm is a contract: `docs/ALGORITHM.md`. A change to it means changing the spec, both engines and the
  equivalence tests in one pull request.
- Public contracts (Python API, CLI flags, exit codes, JSON schemas, `FormatSpec`) need a changelog entry.
- Write docstrings (Google style) in English; keep comments for non-obvious reasons only.

## Reporting bugs

Use the issue templates. A reproducer (command, a few sample lines with secrets removed, `logfold info` output) makes a
fix much faster.
