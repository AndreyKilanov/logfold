"""Option definitions shared by the ``analyze`` and ``diff`` commands."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

import typer

PANEL_INPUT = "Input"
PANEL_OUTPUT = "Output"
PANEL_DIFF = "Diff"
PANEL_MINING = "Mining"
PANEL_EXECUTION = "Execution"
PANEL_GENERAL = "General"

Format = Annotated[
    str,
    typer.Option(
        "--format",
        "-f",
        help="auto, a name from 'logfold formats', regex:<pattern>, or log4j:<pattern>.",
        rich_help_panel=PANEL_INPUT,
    ),
]
Since = Annotated[
    str | None,
    typer.Option(
        "--since",
        metavar="TIME",
        help="Only records at or after this time (ISO 8601, for example 2026-10-06T12:00). A time without a zone is "
        "compared with the times in the log as written; records without a time are left out.",
        rich_help_panel=PANEL_INPUT,
    ),
]
Until = Annotated[
    str | None,
    typer.Option(
        "--until",
        metavar="TIME",
        help="Only records before this time (ISO 8601); see --since.",
        rich_help_panel=PANEL_INPUT,
    ),
]
Multiline = Annotated[
    bool | None,
    typer.Option(
        "--multiline/--no-multiline",
        help="Join continuation lines to the previous record.",
        rich_help_panel=PANEL_INPUT,
    ),
]
Out = Annotated[
    Path | None,
    typer.Option(
        "--out",
        "-o",
        help="Write a report; the suffix selects the format: .html, .json, .txt, .md or .csv (see --report).",
        rich_help_panel=PANEL_OUTPUT,
    ),
]
Append = Annotated[
    bool,
    typer.Option(
        "--append",
        help="Add the --out report to the end of the file instead of replacing it (text and Markdown reports; for "
        "example $GITHUB_STEP_SUMMARY).",
        rich_help_panel=PANEL_OUTPUT,
    ),
]
Report = Annotated[
    str | None,
    typer.Option(
        "--report",
        help="Reporter by name ('logfold plugins list'): it writes the --out file instead of the suffix's reporter, "
        "and without --out it is printed instead of the tables.",
        rich_help_panel=PANEL_OUTPUT,
    ),
]
Top = Annotated[int, typer.Option("--top", "-n", min=1, help="Rows to print per table.", rich_help_panel=PANEL_OUTPUT)]
Examples = Annotated[
    str,
    typer.Option(
        "--examples",
        help="raw, masked or none: how example messages are kept.",
        rich_help_panel=PANEL_OUTPUT,
    ),
]
AsJson = Annotated[
    bool, typer.Option("--json", help="Print JSON to stdout instead of tables.", rich_help_panel=PANEL_OUTPUT)
]
Level = Annotated[
    str | None,
    typer.Option(
        "--level",
        help="Keep templates whose most severe level is at least this: TRACE, DEBUG, INFO, WARN, ERROR or FATAL.",
        rich_help_panel=PANEL_OUTPUT,
    ),
]
OnlyAlerts = Annotated[
    bool,
    typer.Option("--only-alerts", help="Same as --level WARN.", rich_help_panel=PANEL_OUTPUT),
]
SimTh = Annotated[
    float | None,
    typer.Option(
        "--sim-th", min=0.0, max=1.0, help="Similarity threshold (default 0.4).", rich_help_panel=PANEL_MINING
    ),
]
Depth = Annotated[
    int | None, typer.Option("--depth", min=3, help="Template tree depth (default 4).", rich_help_panel=PANEL_MINING)
]
MaxChildren = Annotated[
    int | None,
    typer.Option("--max-children", min=1, help="Children per tree node (default 100).", rich_help_panel=PANEL_MINING),
]
MaxTemplates = Annotated[
    int | None,
    typer.Option(
        "--max-templates",
        min=1,
        help="Template cap before pooling (default 100000).",
        rich_help_panel=PANEL_MINING,
    ),
]
NoMasks = Annotated[
    bool,
    typer.Option("--no-masks", help="Do not mask numbers, IPs, UUIDs and other values.", rich_help_panel=PANEL_MINING),
]
HighCardinality = Annotated[
    bool,
    typer.Option(
        "--high-cardinality",
        help="Fast mode for data with a huge number of distinct messages: at most 5000 templates, runs sequentially.",
        rich_help_panel=PANEL_MINING,
    ),
]
Threads = Annotated[
    int | None,
    typer.Option("--threads", min=1, help="Worker threads (default: all cores).", rich_help_panel=PANEL_EXECUTION),
]
Engine = Annotated[
    str | None,
    typer.Option("--engine", help="auto, native or python (slow reference engine).", rich_help_panel=PANEL_EXECUTION),
]
Strategy = Annotated[
    str | None,
    typer.Option(
        "--strategy",
        help="auto, sequential (one tree) or chunked (parallel).",
        rich_help_panel=PANEL_EXECUTION,
    ),
]
ChunkMb = Annotated[
    int | None,
    typer.Option(
        "--chunk-mb",
        min=1,
        help="Chunk size in MiB for the chunked strategy.",
        rich_help_panel=PANEL_EXECUTION,
    ),
]
WarmStart = Annotated[
    bool,
    typer.Option(
        "--warm-start",
        help="Chunked: start chunks from the tree of the first one (fewer stray templates, slower).",
        rich_help_panel=PANEL_EXECUTION,
    ),
]
Quiet = Annotated[
    bool,
    typer.Option("--quiet", "-q", help="No progress and no status messages on stderr.", rich_help_panel=PANEL_GENERAL),
]
Debug = Annotated[bool, typer.Option("--debug", help="Show tracebacks.", rich_help_panel=PANEL_GENERAL)]


def mining_options(
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
    """Turn the mining flags of a command into keyword arguments of ``logfold.analyze`` and ``logfold.diff``.

    Args:
        sim_th: ``--sim-th``.
        depth: ``--depth``.
        max_children: ``--max-children``.
        max_templates: ``--max-templates``.
        threads: ``--threads``.
        engine: ``--engine``.
        chunk_mb: ``--chunk-mb``.
        strategy: ``--strategy``.
        no_masks: ``--no-masks``.
        high_cardinality: ``--high-cardinality``.
        warm_start: ``--warm-start``.

    Returns:
        The keyword arguments, with ``None`` for every option left at its default.
    """
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
