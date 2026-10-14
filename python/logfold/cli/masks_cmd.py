"""The ``logfold masks`` command group: list the mask sets and show their rules."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape
from rich.table import Table

from logfold.cli import runtime
from logfold.errors import ConfigError, LogfoldError
from logfold.ext import printable, registry
from logfold.ext.mask_sets import MaskSet, load_mask_set

masks_app = typer.Typer(
    name="masks",
    help="List the mask sets (secrets, pii, ...) and show their rules.",
    no_args_is_help=True,
    add_completion=False,
)

AsJson = Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")]


def _safe(text: str) -> str:
    return escape(printable(text))


def _source(name: str) -> str:
    for kind, found, source in registry.plugin_sources():
        if kind == "mask" and found == name:
            return source
    return registry.BUILT_IN


@masks_app.command("list")
def list_command(as_json: AsJson = False) -> None:
    """List the mask sets that --masks accepts, with their version, number of rules and fingerprint."""
    try:
        rows = [(registry.get_mask_set(name), name) for name in registry.mask_set_names()]
    except LogfoldError as error:
        raise runtime.fail(error, debug=False) from None
    if as_json:
        data = [
            {
                "name": mask_set.name,
                "version": mask_set.version,
                "rules": len(mask_set.rules),
                "fingerprint": mask_set.fingerprint,
                "source": _source(name),
                "description": mask_set.description,
            }
            for mask_set, name in rows
        ]
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    console = runtime.stdout_console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for column in ("name", "version", "rules", "fingerprint", "source", "description"):
        table.add_column(column, overflow="fold")
    for mask_set, name in rows:
        table.add_row(
            _safe(mask_set.name),
            str(mask_set.version),
            str(len(mask_set.rules)),
            mask_set.fingerprint,
            _safe(_source(name)),
            _safe(mask_set.description),
        )
    console.print(table)
    console.print(
        "\nUse one with [bold]--masks secrets,pii[/bold] or a set file with [bold]--masks-file FILE[/bold]; "
        "the default masks always run last. Rules: [bold]logfold masks show NAME[/bold]"
    )


def _find(target: str) -> tuple[MaskSet, str]:
    is_file = target.endswith(".json") or "/" in target or "\\" in target
    if is_file:
        path = Path(target)
        return load_mask_set(path), str(path)
    return registry.get_mask_set(target), _source(target)


@masks_app.command("show")
def show_command(
    name: Annotated[str, typer.Argument(help="A set from 'logfold masks list', or the path of a set file (.json).")],
    as_json: AsJson = False,
) -> None:
    """Show the rules of a mask set: name, token, check and pattern, with the fingerprint that a saved state keeps."""
    try:
        mask_set, source = _find(name)
    except (ConfigError, LogfoldError) as error:
        raise runtime.fail(error, debug=False) from None
    if as_json:
        data = {**mask_set.to_dict(), "fingerprint": mask_set.fingerprint, "source": source}
        sys.stdout.write(json.dumps(data, indent=2) + "\n")
        return
    console = runtime.stdout_console()
    console.print(f"[bold]{_safe(mask_set.name)}[/bold] version {mask_set.version}, {len(mask_set.rules)} rules")
    if mask_set.description:
        console.print(_safe(mask_set.description))
    console.print(f"source: {_safe(source)}\nfingerprint: {mask_set.fingerprint}\n")
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for column in ("rule", "token", "check", "pattern"):
        table.add_column(column, overflow="fold")
    for rule in mask_set.rules:
        table.add_row(_safe(rule.name), _safe(rule.token), rule.check or "", _safe(rule.pattern))
    console.print(table)
