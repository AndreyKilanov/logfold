"""The ``logfold`` command: ``analyze``, ``diff``, ``formats`` and ``info``."""

from __future__ import annotations

import codecs
import dataclasses
import errno
import os
import re
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.markup import escape
from rich.progress import DownloadColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

import logfold
from logfold.cli import exit_codes
from logfold.cli.output import printable, render_report, resolve_outputs
from logfold.cli.plugins_cmd import plugins_app
from logfold.cli.render import print_analysis, print_diff
from logfold.engines import native
from logfold.errors import LogfoldError
from logfold.ext import registry
from logfold.ext.formats import JsonFormat, PlainFormat, RegexFormat
from logfold.model import AnalysisResult, DiffResult

app = typer.Typer(
    name="logfold",
    help="Fold large logs into templates and compare two runs.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)
app.add_typer(plugins_app, name="plugins")

Format = Annotated[str, typer.Option("--format", "-f", help="auto, a name from 'logfold formats', or regex:<pattern>.")]
Multiline = Annotated[
    bool | None,
    typer.Option("--multiline/--no-multiline", help="Join continuation lines to the previous record."),
]
Out = Annotated[
    Path | None,
    typer.Option(
        "--out",
        "-o",
        help="Write a report; the suffix selects the format: .html, .json, .txt, .md or .csv (see --report).",
    ),
]
Report = Annotated[
    str | None,
    typer.Option(
        "--report",
        help="Reporter by name ('logfold plugins list'): it writes the --out file instead of the suffix's reporter, "
        "and without --out it is printed instead of the tables.",
    ),
]
Top = Annotated[int, typer.Option("--top", "-n", min=1, help="Rows to print per table.")]
SimTh = Annotated[float | None, typer.Option("--sim-th", min=0.0, max=1.0, help="Similarity threshold (default 0.4).")]
Depth = Annotated[int | None, typer.Option("--depth", min=3, help="Template tree depth (default 4).")]
MaxChildren = Annotated[int | None, typer.Option("--max-children", min=1, help="Children per tree node (default 100).")]
MaxTemplates = Annotated[
    int | None, typer.Option("--max-templates", min=1, help="Template cap before pooling (default 100000).")
]
Threads = Annotated[int | None, typer.Option("--threads", min=1, help="Worker threads (default: all cores).")]
Engine = Annotated[str | None, typer.Option("--engine", help="auto, native or python (slow reference engine).")]
ChunkMb = Annotated[int | None, typer.Option("--chunk-mb", min=1, help="Chunk size in MiB for parallel runs.")]
Strategy = Annotated[str | None, typer.Option("--strategy", help="auto, sequential (one tree) or chunked (parallel).")]
WarmStart = Annotated[
    bool,
    typer.Option(
        "--warm-start", help="Chunked: start chunks from the tree of the first one (fewer stray templates, slower)."
    ),
]
NoMasks = Annotated[bool, typer.Option("--no-masks", help="Do not mask numbers, IPs, UUIDs and other values.")]
HighCardinality = Annotated[
    bool,
    typer.Option(
        "--high-cardinality",
        help="Fast mode for data with a huge number of distinct messages: at most 5000 templates, runs sequentially.",
    ),
]
Examples = Annotated[str, typer.Option("--examples", help="raw, masked or none: how example messages are kept.")]
AsJson = Annotated[bool, typer.Option("--json", help="Print JSON to stdout instead of tables.")]
Quiet = Annotated[bool, typer.Option("--quiet", "-q", help="No progress and no status messages on stderr.")]
Debug = Annotated[bool, typer.Option("--debug", help="Show tracebacks.")]


_SAVED_RESULT_MARKER = re.compile(rb'\{\s*"schema_version"\s*:\s*\d+\s*,\s*"kind"\s*:\s*"analysis"')
_SAVED_RESULT_SNIFF_BYTES = 4096


def _is_saved_result(path: Path) -> bool:
    """Tell whether a file is a JSON analysis report (``analyze --out result.json``) rather than a log."""
    try:
        with path.open("rb") as handle:
            head = handle.read(_SAVED_RESULT_SNIFF_BYTES)
    except OSError:
        return False
    if head.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return True
    return _SAVED_RESULT_MARKER.match(head.removeprefix(codecs.BOM_UTF8).lstrip()) is not None


def _reject_mining_flags(flags: dict[str, bool]) -> None:
    given = [name for name, used in flags.items() if used]
    if given:
        raise logfold.ConfigError(f"{', '.join(given)} cannot be used when comparing saved analysis results")


def _diff_saved(before: Path, after: Path, **options: Any) -> DiffResult:
    return logfold.diff(logfold.load_analysis(before), logfold.load_analysis(after), **options)


def _version(value: bool) -> None:
    if value:
        typer.echo(f"logfold {logfold.__version__}")
        raise typer.Exit()


@app.callback()
def root(
    version: Annotated[
        bool, typer.Option("--version", callback=_version, is_eager=True, help="Show the version.")
    ] = False,
    plugins_dir: Annotated[
        list[Path] | None,
        typer.Option("--plugins-dir", help="Also load plugins from this folder (repeatable)."),
    ] = None,
) -> None:
    """Fold large logs into templates and compare two runs."""
    for folder in plugins_dir or ():
        registry.add_plugin_directory(folder)


def _stdout_console() -> Console:
    return Console(file=sys.stdout, highlight=False)


def _stderr_console() -> Console:
    return Console(file=sys.stderr, highlight=False)


@contextmanager
def _progress(quiet: bool) -> Iterator[Callable[[int], None] | None]:
    if quiet or not sys.stderr.isatty():
        yield None
        return
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        DownloadColumn(),
        TimeElapsedColumn(),
        console=_stderr_console(),
        transient=True,
    ) as progress:
        task = progress.add_task("reading", total=None)
        yield lambda consumed: progress.advance(task, consumed)


def _fail(error: Exception, debug: bool) -> typer.Exit:
    if debug:
        raise error
    _stderr_console().print(f"[red]error:[/red] {error}", highlight=False, markup=True)
    return typer.Exit(exit_codes.ERROR)


def _write_report(result: AnalysisResult | DiffResult, out: Path, reporter: str, quiet: bool) -> None:
    out.write_text(render_report(result, reporter), encoding="utf-8")
    if not quiet:
        _stderr_console().print(f"wrote {out}", highlight=False)


def _emit(result: AnalysisResult | DiffResult, top: int, reporter: str | None) -> None:
    if reporter is not None:
        text = render_report(result, reporter, top)
        sys.stdout.write(printable(text) if sys.stdout.isatty() else text)
        return
    if sys.stdout.isatty():
        console = _stdout_console()
        if isinstance(result, DiffResult):
            print_diff(console, result, top)
        else:
            print_analysis(console, result, top)
        return
    sys.stdout.write(result.render("text", top=top))


def _options(
    sim_th: float | None,
    depth: int | None,
    max_children: int | None,
    max_templates: int | None,
    threads: int | None,
    engine: str | None,
    chunk_mb: int | None,
    strategy: str | None,
    no_masks: bool,
    high_cardinality: bool,
    warm_start: bool,
) -> dict[str, Any]:
    return {
        "sim_th": sim_th,
        "depth": depth,
        "max_children": max_children,
        "max_templates": max_templates,
        "threads": threads,
        "engine": engine,
        "chunk_bytes": chunk_mb << 20 if chunk_mb else None,
        "strategy": strategy,
        "masks": [] if no_masks else None,
        "high_cardinality": high_cardinality,
        "warm_start": True if warm_start else None,
    }


@app.command()
def analyze(
    files: Annotated[list[Path], typer.Argument(help="Log files forming one run ('-' reads standard input).")],
    format: Format = "auto",
    multiline: Multiline = None,
    top: Top = 20,
    min_count: Annotated[
        int,
        typer.Option(
            "--min-count",
            min=1,
            help="Hide templates with fewer records; a .json file from --out stays complete.",
        ),
    ] = 1,
    out: Out = None,
    report: Report = None,
    sim_th: SimTh = None,
    depth: Depth = None,
    max_children: MaxChildren = None,
    max_templates: MaxTemplates = None,
    threads: Threads = None,
    engine: Engine = None,
    chunk_mb: ChunkMb = None,
    strategy: Strategy = None,
    no_masks: NoMasks = False,
    high_cardinality: HighCardinality = False,
    warm_start: WarmStart = False,
    examples: Examples = "raw",
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Fold FILES into message templates and count them."""
    try:
        outputs = resolve_outputs("analysis", out, report, as_json)
        with _progress(quiet) as progress:
            result = logfold.analyze(
                [str(f) for f in files],
                format=format,
                multiline=multiline,
                examples=examples,  # type: ignore[arg-type]
                progress=progress,
                **_options(
                    sim_th,
                    depth,
                    max_children,
                    max_templates,
                    threads,
                    engine,
                    chunk_mb,
                    strategy,
                    no_masks,
                    high_cardinality,
                    warm_start,
                ),
            )
        shown = result
        if min_count > 1:
            shown = dataclasses.replace(result, templates=tuple(t for t in result.templates if t.count >= min_count))
        _emit(shown, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            _write_report(result if outputs.file == "json" else shown, out, outputs.file, quiet)
    except LogfoldError as error:
        raise _fail(error, debug) from None


@app.command()
def diff(
    before: Annotated[
        Path, typer.Argument(help="Log file of the first run, for example before a deploy, or a saved report.")
    ],
    after: Annotated[Path, typer.Argument(help="Log file of the second run, or a saved report.")],
    format: Format = "auto",
    multiline: Multiline = None,
    top: Top = 20,
    threshold_ratio: Annotated[
        float, typer.Option("--threshold-ratio", min=1.0, help="Share change factor reported as 'changed'.")
    ] = 2.0,
    min_count: Annotated[int, typer.Option("--min-count", min=0, help="Records needed to report 'changed'.")] = 10,
    min_new_count: Annotated[
        int, typer.Option("--min-new-count", min=0, help="Records needed to report new or disappeared.")
    ] = 1,
    matcher: Annotated[
        str, typer.Option("--matcher", help="Diff matcher: jaccard, token_subset or exact.")
    ] = "jaccard",
    recount: Annotated[
        bool, typer.Option("--recount/--no-recount", help="Assign records to the finished tree (slower, consistent).")
    ] = True,
    fail_on_new: Annotated[
        bool, typer.Option("--fail-on-new", help="Exit with code 2 when new templates are found.")
    ] = False,
    fail_on_new_alerts: Annotated[
        bool, typer.Option("--fail-on-new-alerts", help="Exit with code 2 when new WARN/ERROR/FATAL templates exist.")
    ] = False,
    out: Out = None,
    report: Report = None,
    sim_th: SimTh = None,
    depth: Depth = None,
    max_children: MaxChildren = None,
    max_templates: MaxTemplates = None,
    threads: Threads = None,
    engine: Engine = None,
    chunk_mb: ChunkMb = None,
    strategy: Strategy = None,
    no_masks: NoMasks = False,
    high_cardinality: HighCardinality = False,
    warm_start: WarmStart = False,
    examples: Examples = "raw",
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Compare two runs: new, disappeared and changed templates.

    Each argument is a log file or a saved report of 'logfold analyze --out result.json'; both must be of one kind.
    """
    try:
        outputs = resolve_outputs("diff", out, report, as_json)
        for path in (before, after):
            if not path.is_file():
                raise logfold.SourceError(f"cannot read {str(path)!r}: no such file")
        saved = (_is_saved_result(before), _is_saved_result(after))
        if saved[0] != saved[1]:
            raise logfold.ConfigError("diff compares two log files or two saved analysis reports, not one of each")
        if all(saved):
            _reject_mining_flags(
                {
                    "--format": format != "auto",
                    "--multiline/--no-multiline": multiline is not None,
                    "--no-recount": not recount,
                    "--sim-th": sim_th is not None,
                    "--depth": depth is not None,
                    "--max-children": max_children is not None,
                    "--max-templates": max_templates is not None,
                    "--threads": threads is not None,
                    "--engine": engine is not None,
                    "--chunk-mb": chunk_mb is not None,
                    "--strategy": strategy is not None,
                    "--no-masks": no_masks,
                    "--high-cardinality": high_cardinality,
                    "--warm-start": warm_start,
                }
            )
            result = _diff_saved(
                before,
                after,
                threshold_ratio=threshold_ratio,
                min_count=min_count,
                min_new_count=min_new_count,
                matcher=matcher,
                examples=examples,
            )
        else:
            with _progress(quiet) as progress:
                result = logfold.diff(
                    str(before),
                    str(after),
                    format=format,
                    multiline=multiline,
                    threshold_ratio=threshold_ratio,
                    min_count=min_count,
                    min_new_count=min_new_count,
                    matcher=matcher,
                    recount=recount,
                    examples=examples,  # type: ignore[arg-type]
                    progress=progress,
                    **_options(
                        sim_th,
                        depth,
                        max_children,
                        max_templates,
                        threads,
                        engine,
                        chunk_mb,
                        strategy,
                        no_masks,
                        high_cardinality,
                        warm_start,
                    ),
                )
        _emit(result, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            _write_report(result, out, outputs.file, quiet)
    except LogfoldError as error:
        raise _fail(error, debug) from None
    if fail_on_new and result.new_templates:
        raise typer.Exit(exit_codes.NEW_TEMPLATES)
    if fail_on_new_alerts and result.new_alerts:
        raise typer.Exit(exit_codes.NEW_TEMPLATES)


def _describe(spec: PlainFormat | JsonFormat | RegexFormat) -> tuple[str, str]:
    if isinstance(spec, RegexFormat):
        return "regex", spec.pattern
    if isinstance(spec, JsonFormat):
        return "json", f"message: {', '.join(spec.message_keys)}; time: {', '.join(spec.time_keys)}"
    return "plain", "whole line"


@app.command()
def formats() -> None:
    """List the available log formats."""
    console = _stdout_console()
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("name")
    table.add_column("kind")
    table.add_column("details", overflow="fold")
    for name in registry.format_names():
        kind, details = _describe(registry.get_format(name))
        table.add_row(escape(name), kind, escape(details))
    console.print(table)
    console.print(
        "\nUse [bold]regex:<pattern>[/bold] for a custom format. "
        "Named groups message/msg, timestamp/ts/time and level/lvl are picked up."
    )


@app.command()
def info() -> None:
    """Show versions and engine availability (useful in bug reports)."""
    console = _stdout_console()
    console.print(f"logfold {logfold.__version__}")
    console.print(f"python {sys.version.split()[0]}")
    versions = native.core_versions()
    if native.is_available() and versions is not None:
        console.print(
            f"native engine: available (core {versions['core']}, contract {versions['contract']}, "
            f"algo {versions['algo']})"
        )
    else:
        console.print("native engine: [yellow]not available[/yellow] (the slow pure-Python engine will be used)")
    console.print(f"formats: {', '.join(registry.format_names())}")
    console.print(f"reporters: {', '.join(registry.reporter_names())}")


CLOSED_PIPE_ERRNOS = frozenset({errno.EPIPE, errno.EINVAL})
"""Errors of a write to a pipe whose reader has gone; Windows reports ``EINVAL`` instead of ``EPIPE``."""


def _is_closed_pipe(error: OSError) -> bool:
    return error.errno in CLOSED_PIPE_ERRNOS and not sys.stdout.isatty()


def _silence_stdout() -> None:
    """Point standard output at the null device so the final flush at interpreter exit cannot fail again."""
    devnull = os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, sys.stdout.fileno())
    os.close(devnull)


def run() -> None:
    """Run the app with UTF-8 safe output streams.

    A reader that closes the pipe early (``logfold info | head``) ends the command quietly with the error exit code.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    try:
        app()
    except KeyboardInterrupt:
        _stderr_console().print("interrupted", highlight=False)
        raise SystemExit(exit_codes.INTERRUPTED) from None
    except OSError as error:
        if not _is_closed_pipe(error):
            raise
        _silence_stdout()
        raise SystemExit(exit_codes.ERROR) from None
