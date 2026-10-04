"""Command line interface of logfold."""

from __future__ import annotations

import sys

INSTALL_HINT = (
    "the logfold command needs the optional CLI dependencies; install them with:\n"
    "    pip install 'logfold[cli]'    (or: pipx install 'logfold[cli]')"
)


def main() -> None:
    """Entry point of the ``logfold`` console script."""
    try:
        from logfold.cli.app import run  # noqa: PLC0415 - optional dependencies
    except ImportError as error:
        sys.stderr.write(f"{INSTALL_HINT}\n({error})\n")
        raise SystemExit(1) from None
    run()


__all__ = ["main"]
