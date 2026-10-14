"""Option definitions shared by the ``analyze`` and ``diff`` commands."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Any

import typer

from logfold.errors import ConfigError
from logfold.ext.mask_sets import MaskSet, load_mask_set

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
        help="Write a report; the suffix selects it: .html .json .txt .md .csv .xml (JUnit) .prom (see --report).",
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
LoadState = Annotated[
    Path | None,
    typer.Option(
        "--load-state",
        metavar="FILE",
        help="Continue from the miner that an earlier run saved (same masks and parameters); the report counts only "
        "this run. A big input is continued in parallel; --strategy sequential is exact.",
        rich_help_panel=PANEL_INPUT,
    ),
]
SaveState = Annotated[
    Path | None,
    typer.Option(
        "--save-state",
        metavar="FILE",
        help="Save the trained miner (templates and counts, no example lines) for a later run; a .gz path is "
        "compressed.",
        rich_help_panel=PANEL_OUTPUT,
    ),
]
StateForm = Annotated[
    str,
    typer.Option(
        "--state-format",
        help="json (readable) or binary (compact, for very large states): the form of --save-state.",
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
OnFull = Annotated[
    str | None,
    typer.Option(
        "--on-full",
        help="At --max-templates: pool (default) puts new shapes into catch-all templates, evict drops the least "
        "recently used templates and keeps learning (one tree, so --strategy sequential).",
        rich_help_panel=PANEL_MINING,
    ),
]
Delimiters = Annotated[
    str | None,
    typer.Option(
        "--delimiters",
        metavar="CHARS",
        help="The characters that separate tokens, replacing the default (space, tab, CR, LF): \\t, \\n, \\r and \\\\ "
        "are read as escapes. Keep the whitespace when you add one, for example ' \\t\\n\\r_='.",
        rich_help_panel=PANEL_MINING,
    ),
]
NoMasks = Annotated[
    bool,
    typer.Option("--no-masks", help="Do not mask numbers, IPs, UUIDs and other values.", rich_help_panel=PANEL_MINING),
]
Masks = Annotated[
    str | None,
    typer.Option(
        "--masks",
        metavar="NAMES",
        help="Mask sets that run before the default masks, comma-separated, for example secrets,pii "
        "('logfold masks list' shows them).",
        rich_help_panel=PANEL_MINING,
    ),
]
MasksFile = Annotated[
    list[Path] | None,
    typer.Option(
        "--masks-file",
        metavar="FILE",
        help="A mask set from a JSON file (see docs/plugins.md); repeat the flag for several. Runs after --masks.",
        rich_help_panel=PANEL_MINING,
    ),
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
    typer.Option(
        "--engine", help="auto or native (python is deprecated and runs native).", rich_help_panel=PANEL_EXECUTION
    ),
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


ESCAPES = {"t": "\t", "n": "\n", "r": "\r", "\\": "\\"}


def read_delimiters(text: str | None) -> str | None:
    """Read the escapes for a tab, a line feed, a carriage return and a backslash in a ``--delimiters`` value.

    Args:
        text: The value as typed, or ``None`` when the flag was not given.

    Returns:
        The characters, or ``None``.

    Raises:
        ConfigError: If a backslash is followed by anything else, or ends the value.
    """
    if text is None:
        return None
    out: list[str] = []
    chars = iter(text)
    for char in chars:
        if char != "\\":
            out.append(char)
            continue
        escaped = next(chars, "")
        if escaped not in ESCAPES:
            raise ConfigError(
                f"unknown escape '\\{escaped}' in --delimiters",
                hint="write a tab as \\t, a line feed as \\n, a carriage return as \\r and a backslash as \\\\",
            )
        out.append(ESCAPES[escaped])
    return "".join(out)


def read_masks(
    no_masks: bool, masks: str | None = None, masks_files: Sequence[Path] | None = None
) -> list[str | MaskSet] | None:
    """Turn the mask flags of a command into the ``masks`` argument of the library.

    Args:
        no_masks: ``--no-masks``.
        masks: ``--masks``, comma-separated set names.
        masks_files: ``--masks-file``, once for every file.

    Returns:
        ``[]`` for ``--no-masks``, the named sets followed by the sets of the files, or ``None`` when no flag was given
        (the settings file or the defaults then decide).

    Raises:
        ConfigError: If ``--no-masks`` is combined with another mask flag, a name is empty, or a file cannot be used.
    """
    names = [name.strip() for name in masks.split(",")] if masks is not None else []
    if masks is not None and not all(names):
        raise ConfigError("--masks needs set names separated by commas", hint="for example --masks secrets,pii")
    files = list(masks_files or [])
    if no_masks:
        if names or files:
            raise ConfigError("--no-masks cannot be combined with --masks or --masks-file")
        return []
    if not names and not files:
        return None
    return [*names, *(load_mask_set(path) for path in files)]


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
    on_full: str | None = None,
    delimiters: str | None = None,
    masks: str | None = None,
    masks_files: Sequence[Path] | None = None,
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
        on_full: ``--on-full``.
        delimiters: ``--delimiters``, with the escapes not yet read.
        masks: ``--masks``.
        masks_files: ``--masks-file``.

    Returns:
        The keyword arguments, with ``None`` for every option left at its default.
    """
    return {
        "sim_th": sim_th,
        "depth": depth,
        "max_children": max_children,
        "max_templates": max_templates,
        "on_full": on_full,
        "delimiters": read_delimiters(delimiters),
        "threads": threads,
        "engine": engine,
        "chunk_bytes": chunk_mb << 20 if chunk_mb else None,
        "strategy": strategy,
        "masks": read_masks(no_masks, masks, masks_files),
        "high_cardinality": high_cardinality,
        "warm_start": True if warm_start else None,
    }
