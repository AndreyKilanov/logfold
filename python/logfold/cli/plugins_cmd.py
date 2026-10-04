"""The ``logfold plugins`` command group: list, check and install plugins."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from logfold.cli import exit_codes
from logfold.errors import LogfoldError
from logfold.ext import registry
from logfold.plugins import catalog as plugin_catalog
from logfold.plugins import templates

plugins_app = typer.Typer(
    name="plugins",
    help="List, check and install logfold plugins (formats, reporters, diff matchers).",
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


def _stderr() -> Console:
    return Console(file=sys.stderr, highlight=False)


def _fail(error: Exception) -> typer.Exit:
    _stderr().print(f"[red]error:[/red] {escape(str(error))}", highlight=False, soft_wrap=True)
    return typer.Exit(exit_codes.ERROR)


def _load(online: bool, catalog: str | None) -> plugin_catalog.Catalog:
    try:
        return plugin_catalog.load(catalog, online)
    except LogfoldError as error:
        raise _fail(error) from None


@plugins_app.command("list")
def list_plugins(as_json: AsJson = False) -> None:
    """List the formats, reporters and diff matchers that are available, and where each one comes from."""
    rows = registry.plugin_sources()
    if as_json:
        payload = [{"kind": kind, "name": name, "source": source} for kind, name, source in rows]
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        return
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    for column in ("kind", "name", "source"):
        table.add_column(column, overflow="fold")
    for kind, name, source in rows:
        table.add_row(kind, escape(name), escape(source))
    _stdout().print(table)


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
        source = templates.render_template(kind, name)
    except LogfoldError as error:
        raise _fail(error) from None
    target_dir = folder if folder is not None else registry.default_plugin_dir()
    target = target_dir / f"{templates.module_stem(name)}.py"
    if target.exists() and not force:
        raise _fail(LogfoldError(f"{target} already exists; use --force to overwrite it"))
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        target.write_text(source, encoding="utf-8")
    except OSError as error:
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
    loaded = _load(online, catalog)
    entry = loaded.find(name)
    if entry is None:
        known = ", ".join(e.name for e in loaded.entries) or "none"
        raise _fail(LogfoldError(f"unknown plugin {name!r}; the catalog has: {known}"))
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
        raise _fail(LogfoldError(f"pip failed with exit code {code}"))
    console.print(f"Installed {escape(entry.package)}. Run 'logfold plugins list' to see what it adds.")
