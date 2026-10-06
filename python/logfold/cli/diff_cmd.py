"""The ``logfold diff`` command."""

from __future__ import annotations

import codecs
import re
from pathlib import Path
from typing import Annotated, Any

import typer

import logfold
from logfold.cli import exit_codes
from logfold.cli.options import (
    AsJson,
    ChunkMb,
    Debug,
    Depth,
    Engine,
    Examples,
    Format,
    HighCardinality,
    MaxChildren,
    MaxTemplates,
    Multiline,
    NoMasks,
    Out,
    Quiet,
    Report,
    SimTh,
    Strategy,
    Threads,
    Top,
    WarmStart,
    mining_options,
)
from logfold.cli.output import resolve_outputs
from logfold.cli.runtime import emit, fail, progress_reporter, write_report
from logfold.errors import LogfoldError
from logfold.model import DiffResult

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
            with progress_reporter(quiet) as progress:
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
                    **mining_options(
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
        emit(result, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(result, out, outputs.file, quiet)
    except LogfoldError as error:
        raise fail(error, debug) from None
    if fail_on_new and result.new_templates:
        raise typer.Exit(exit_codes.NEW_TEMPLATES)
    if fail_on_new_alerts and result.new_alerts:
        raise typer.Exit(exit_codes.NEW_TEMPLATES)
