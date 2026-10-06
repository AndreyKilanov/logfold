"""The ``logfold analyze`` command."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Annotated

import typer

import logfold
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
        with progress_reporter(quiet) as progress:
            result = logfold.analyze(
                [str(f) for f in files],
                format=format,
                multiline=multiline,
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
        shown = result
        if min_count > 1:
            shown = dataclasses.replace(result, templates=tuple(t for t in result.templates if t.count >= min_count))
        emit(shown, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(result if outputs.file == "json" else shown, out, outputs.file, quiet)
    except LogfoldError as error:
        raise fail(error, debug) from None
