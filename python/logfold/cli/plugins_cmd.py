"""The ``logfold plugins`` command group: list, check and install plugins."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from logfold.cli import runtime
from logfold.errors import LogfoldError
from logfold.ext import printable, registry
from logfold.plugins import listing as plugin_listing
from logfold.plugins import templates

if TYPE_CHECKING:
    from logfold.plugins.catalog import Catalog
    from logfold.plugins.listing import PluginInfo

plugins_app = typer.Typer(
    name="plugins",
    help="List, inspect, check and install logfold plugins (formats, reporters, diff matchers).",
    no_args_is_help=True,
    add_completion=False,
)

Online = Annotated[
    bool,
    typer.Option("--online", help="Fetch the latest catalog over HTTPS instead of the one bundled with logfold."),
]
CatalogSource = Annotated[
    str | None,
    typer.Option("--catalog", help="Catalog file or HTTPS URL; overrides --online."),
]
AsJson = Annotated[bool, typer.Option("--json", help="Print JSON instead of a table.")]


def _stdout() -> Console:
    return Console(file=sys.stdout, highlight=False)


def _fail(error: Exception) -> typer.Exit:
    return runtime.fail(error, debug=False)


def _load(online: bool, catalog: str | None) -> Catalog:
    from logfold.plugins import catalog as plugin_catalog  # noqa: PLC0415 - slow imports

    try:
        return plugin_catalog.load(catalog, online)
    except LogfoldError as error:
        raise _fail(error) from None


Kind = Annotated[str | None, typer.Option("--kind", "-k", help="Only this kind: format, reporter or matcher.")]
_USAGE = {"format": "--format {name}", "reporter": "--report {name}", "matcher": "--matcher {name}"}


def _safe(text: str) -> str:
    return escape(printable(text))


def _row(info: PluginInfo) -> dict[str, object]:
    return {
        "kind": info.kind,
        "name": info.name,
        "status": info.status,
        "source": info.source,
        "package": info.package,
        "version": info.version,
        "description": info.description,
        "requirement": info.requirement,
        "install": info.install,
        "homepage": info.homepage,
        "min_logfold": info.min_logfold,
        "compatible": info.compatible,
    }


@plugins_app.command("list")
def list_command(
    installed: Annotated[bool, typer.Option("--installed", help="Only what is built in or installed.")] = False,
    available: Annotated[
        bool, typer.Option("--available", help="Only plugins of the catalog not installed yet.")
    ] = False,
    kind: Kind = None,
    online: Online = False,
    catalog: CatalogSource = None,
    as_json: AsJson = False,
) -> None:
    """List formats, reporters and diff matchers: built in, installed, and available from the catalog.

    The catalog bundled with this version of logfold is used and nothing is downloaded; --online fetches the latest one.
    """
    if installed and available:
        raise _fail(LogfoldError("--installed and --available exclude each other; leave both out to see everything"))
    loaded = _load(online, catalog)
    status = ("built-in", "installed") if installed else ("available",) if available else None
    try:
        rows = plugin_listing.list_plugins(kind=kind, status=status, catalog=loaded)
    except LogfoldError as error:
        raise _fail(error) from None
    if as_json:
        sys.stdout.write(json.dumps([_row(row) for row in rows], indent=2) + "\n")
        return
    console = _stdout()
    if not rows:
        console.print("No plugins match.")
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for column in ("kind", "name", "status", "source", "description"):
        table.add_column(column, overflow="fold")
    for row in rows:
        origin = row.requirement or ("" if row.status == "built-in" else row.source)
        about = row.description if row.compatible else f"{row.description} [needs logfold {row.min_logfold}]".strip()
        table.add_row(row.kind, _safe(row.name), row.status, _safe(origin), _safe(about))
    console.print(table)
    if any(row.status == "available" for row in rows):
        console.print(
            "\nInstall one with: [bold]logfold plugins install NAME[/bold]; "
            "details: [bold]logfold plugins info NAME[/bold]"
        )


@plugins_app.command("info")
def info_command(
    name: Annotated[str, typer.Argument(help="Plugin name from 'logfold plugins list'.")],
    kind: Kind = None,
    online: Online = False,
    catalog: CatalogSource = None,
    as_json: AsJson = False,
) -> None:
    """Show what a plugin is, where it comes from, how to install it and how to use it."""
    loaded = _load(online, catalog)
    try:
        rows = plugin_listing.plugin_info(name, kind=kind, catalog=loaded)
    except LogfoldError as error:
        raise _fail(error) from None
    if as_json:
        sys.stdout.write(json.dumps([_row(row) for row in rows], indent=2) + "\n")
        return
    console = _stdout()
    for number, row in enumerate(rows):
        if number:
            console.print()
        console.print(f"[bold]{_safe(row.name)}[/bold] ({row.kind}, {row.status})")
        if row.description:
            console.print(f"about:    {_safe(row.description)}")
        console.print(f"source:   {_safe(row.source)}", soft_wrap=True)
        if row.package:
            console.print(f"package:  {_safe(row.package)}{' ' + row.version if row.version else ''}", soft_wrap=True)
        if row.homepage:
            console.print(f"homepage: {_safe(row.homepage)}", soft_wrap=True)
        if row.min_logfold:
            note = "" if row.compatible else " (newer than the logfold you run: it cannot be installed)"
            console.print(f"needs:    logfold {_safe(row.min_logfold)} or newer{note}")
        if row.install and row.compatible:
            console.print(
                f"install:  [bold]{_safe(row.install)}[/bold]  (pip requirement: {_safe(row.requirement or '')})"
            )
        elif row.status != "available":
            console.print(f"use:      [bold]{_safe(_USAGE[row.kind].format(name=row.name))}[/bold]")


@plugins_app.command("dir")
def show_folders() -> None:
    """Show where logfold looks for your own plugins (Python files and packages)."""
    console = _stdout()
    default = registry.default_plugin_dir()
    state = "exists" if default.is_dir() else "does not exist yet"
    console.print(f"plugin folder:       {escape(str(default))} ({state})", soft_wrap=True)
    extra = [part for part in os.environ.get(registry.ENV_PLUGIN_PATH, "").split(os.pathsep) if part]
    shown = escape(os.pathsep.join(extra)) if extra else "not set"
    console.print(f"{registry.ENV_PLUGIN_PATH}: {shown}", soft_wrap=True)
    if registry.plugin_directories():
        console.print(
            "Add a plugin with: [bold]logfold plugins new KIND NAME[/bold]  (KIND: format, reporter, matcher)"
        )
    else:
        console.print(f"These folders are switched off by {registry.ENV_NO_USER_PLUGINS}.")


@plugins_app.command("new")
def new_plugin(
    kind: Annotated[str, typer.Argument(help="format, reporter or matcher.")],
    name: Annotated[str, typer.Argument(help="Plugin name: letters, digits, '-' and '_'.")],
    folder: Annotated[Path | None, typer.Option("--dir", help="Write here instead of the plugin folder.")] = None,
    force: Annotated[bool, typer.Option("--force", help="Overwrite an existing file.")] = False,
) -> None:
    """Write a working plugin template into your plugin folder, ready to edit."""
    try:
        target = templates.write_template(kind, name, folder, force)
    except LogfoldError as error:
        raise _fail(error) from None
    console = _stdout()
    console.print(f"Wrote {escape(str(target))}", soft_wrap=True)
    if folder is not None and folder not in registry.plugin_directories():
        console.print(f"Use it with: [bold]logfold --plugins-dir {escape(str(folder))} ...[/bold]", soft_wrap=True)
    console.print("Edit it, then check that logfold sees it: [bold]logfold plugins list[/bold]")


@plugins_app.command("check")
def check(online: Online = False, catalog: CatalogSource = None, as_json: AsJson = False) -> None:
    """Show the plugins of the catalog that are not installed yet.

    By default the catalog bundled with this version of logfold is used and nothing is downloaded. --online fetches the
    latest one over HTTPS; set LOGFOLD_OFFLINE=1 to forbid that.
    """
    from logfold.plugins import catalog as plugin_catalog  # noqa: PLC0415 - slow imports

    loaded = _load(online, catalog)
    new = plugin_catalog.new_plugins(loaded)
    if as_json:
        payload = {
            "catalog": loaded.source,
            "new": [
                {
                    "name": e.name,
                    "kinds": list(e.kinds),
                    "package": e.package,
                    "requirement": e.requirement,
                    "description": e.description,
                    "homepage": e.homepage,
                    "min_logfold": e.min_logfold,
                    "compatible": e.fits(),
                }
                for e in new
            ],
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return
    console = _stdout()
    console.print(f"catalog: {escape(loaded.source)}, {len(loaded.entries)} plugin(s), {len(new)} not installed")
    if not new:
        console.print("No new plugins.")
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for column in ("name", "kinds", "package", "description"):
        table.add_column(column, overflow="fold")
    for entry in new:
        table.add_row(escape(entry.name), ", ".join(entry.kinds), escape(entry.requirement), escape(entry.description))
    console.print(table)
    console.print("\nInstall one with: [bold]logfold plugins install NAME[/bold]")


@plugins_app.command("install")
def install(
    name: Annotated[str, typer.Argument(help="Plugin name from 'logfold plugins check'.")],
    online: Online = False,
    catalog: CatalogSource = None,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask for confirmation.")] = False,
) -> None:
    """Install a plugin of the catalog with pip into the environment that runs logfold.

    A plugin is Python code that runs with your privileges: only plugins of the catalog can be installed, and the
    package and version are shown before anything happens.
    """
    from logfold.plugins import catalog as plugin_catalog  # noqa: PLC0415 - slow imports

    loaded = _load(online, catalog)
    entry = loaded.find(name)
    if entry is None:
        known = ", ".join(e.name for e in loaded.entries) or "none"
        raise _fail(LogfoldError(f"unknown plugin {name!r}; the catalog has: {known}"))
    try:
        plugin_catalog.require_compatible(entry)
    except LogfoldError as error:
        raise _fail(error) from None
    console = _stdout()
    if plugin_catalog.is_installed(entry.package):
        console.print(f"{escape(entry.package)} is already installed.")
        return
    console.print(f"plugin:   {escape(entry.name)} ({', '.join(entry.kinds)})")
    console.print(f"package:  {escape(entry.requirement)}")
    if entry.description:
        console.print(f"about:    {escape(entry.description)}")
    if entry.homepage:
        console.print(f"homepage: {escape(entry.homepage)}")
    console.print(f"catalog:  {escape(loaded.source)}")
    if not yes and not typer.confirm("Install it? It will run code on this machine", default=False):
        raise _fail(LogfoldError("cancelled"))
    try:
        code = plugin_catalog.install(entry)
    except LogfoldError as error:
        raise _fail(error) from None
    if code != 0:
        raise _fail(LogfoldError(f"the installer failed with exit code {code}"))
    console.print(f"Installed {escape(entry.package)}. Run 'logfold plugins list' to see what it adds.")
