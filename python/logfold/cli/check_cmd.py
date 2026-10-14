"""The ``logfold check`` command: does a log hold anything that a saved model does not know?"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.markup import escape

import logfold
from logfold.cli import exit_codes
from logfold.cli.levels import diff_note, resolve_level
from logfold.cli.options import (
    PANEL_INPUT,
    PANEL_OUTPUT,
    Append,
    AsJson,
    Debug,
    Delimiters,
    Depth,
    Examples,
    Format,
    Level,
    Masks,
    MasksFile,
    MaxChildren,
    MaxTemplates,
    Multiline,
    NoMasks,
    OnFull,
    OnlyAlerts,
    Out,
    Quiet,
    Report,
    SimTh,
    Since,
    Top,
    Until,
    mining_options,
)
from logfold.cli.output import render_report, resolve_outputs
from logfold.cli.render import print_diff
from logfold.cli.runtime import (
    config_note,
    examples_note,
    fail,
    note,
    progress_reporter,
    settings_of,
    stdout_console,
    write_report,
    write_stdout,
)
from logfold.errors import ConfigError, LogfoldError
from logfold.ext.text import printable
from logfold.model_check import CheckResult

EXAMPLES = """Examples:

  logfold analyze good.log --save-state model.json

  logfold check app.log --state model.json

  logfold check app.log --state model.json --max-unmatched 0.5 --fail-on new

  logfold check app.log --state model.json --report github-summary --out "$GITHUB_STEP_SUMMARY" --append

  logfold check app.log --state model.json --json > check.json

Exit codes: 0 passed, 1 error, 2 a finding."""

NOT_FOR_CHECK = ("engine", "high_cardinality", "warm_start", "threads", "strategy", "chunk_bytes")
MAX_UNMATCHED_DEFAULT = "1"


def _limit(text: str) -> float | None:
    if text.strip().lower() == "off":
        return None
    try:
        return float(text)
    except ValueError:
        raise ConfigError(f"--max-unmatched is a number from 0 to 100 (percent) or 'off', found {text!r}") from None


def _header(result: CheckResult) -> str:
    unmatched = result.unmatched
    records = result.diff.after.records
    summary = (
        f"{records:,} records, {unmatched.records:,} fit no template of the model ({result.unmatched_share:.2%}), "
        f"{len(result.diff.new_templates):,} new templates, {len(result.diff.changed):,} changed"
    )
    lines = [f"check {'passed' if result.passed else 'FAILED'}: {summary}"]
    lines.extend(f"  - {finding.message}" for finding in result.findings)
    return "\n".join(lines)


def _emit(result: CheckResult, top: int, reporter: str | None) -> None:
    if reporter is not None:
        text = render_report(result, reporter, top)
        write_stdout(printable(text) if sys.stdout.isatty() else text)
        return
    header = _header(result)
    if sys.stdout.isatty():
        console = stdout_console()
        style = "green" if result.passed else "bold red"
        console.print(f"[{style}]{escape(printable(header))}[/{style}]", highlight=False)
        print_diff(console, result.diff, top)
        return
    write_stdout(header + "\n\n" + result.render("text", top=top))


def check(
    ctx: typer.Context,
    files: Annotated[list[Path], typer.Argument(help="Log files forming one run ('-' reads standard input).")],
    state: Annotated[
        Path,
        typer.Option(
            "--state",
            metavar="MODEL",
            help="State file saved by 'logfold analyze --save-state' (or 'logfold learn'); it is only read.",
            rich_help_panel=PANEL_INPUT,
        ),
    ],
    format: Format = "auto",
    multiline: Multiline = None,
    since: Since = None,
    until: Until = None,
    max_unmatched: Annotated[
        str,
        typer.Option(
            "--max-unmatched",
            metavar="PERCENT",
            help="The highest share of records, in percent, that may fit no template of the model, or 'off'.",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = MAX_UNMATCHED_DEFAULT,
    fail_on: Annotated[
        str,
        typer.Option(
            "--fail-on",
            metavar="WHAT",
            help="Which new templates fail the check: new-alerts (WARN and above), new (any) or none (only report).",
            rich_help_panel=PANEL_INPUT,
        ),
    ] = "new-alerts",
    significance: Annotated[
        float | None,
        typer.Option(
            "--significance",
            min=0.0,
            max=1.0,
            help="Highest p-value of a changed template that is still reported (default 0.01).",
            rich_help_panel=PANEL_OUTPUT,
        ),
    ] = None,
    top: Top = 20,
    level: Level = None,
    only_alerts: OnlyAlerts = False,
    out: Out = None,
    append: Append = False,
    report: Report = None,
    sim_th: SimTh = None,
    depth: Depth = None,
    max_children: MaxChildren = None,
    max_templates: MaxTemplates = None,
    on_full: OnFull = None,
    delimiters: Delimiters = None,
    no_masks: NoMasks = False,
    masks: Masks = None,
    masks_file: MasksFile = None,
    examples: Examples = "raw",
    as_json: AsJson = False,
    quiet: Quiet = False,
    debug: Debug = False,
) -> None:
    """Check FILES against a saved model: report what it does not know and fail when that is too much."""
    try:
        settings = settings_of(ctx)
        config_note(settings, quiet)
        examples_note(settings, masks, masks_file, examples, quiet)
        outputs = resolve_outputs("diff", out, report, as_json, append)
        threshold = resolve_level(level, only_alerts)
        options = mining_options(
            sim_th,
            depth,
            max_children,
            max_templates,
            None,
            None,
            None,
            None,
            no_masks,
            False,
            False,
            on_full,
            delimiters,
            masks,
            masks_file,
        )
        for name in NOT_FOR_CHECK:
            del options[name]
        with progress_reporter(quiet) as progress:
            result = logfold.check(
                state,
                [str(f) for f in files],
                max_unmatched=_limit(max_unmatched),
                fail_on=fail_on,  # type: ignore[arg-type]
                significance=significance,
                format=format,
                multiline=multiline,
                since=since,
                until=until,
                examples=examples,  # type: ignore[arg-type]
                progress=progress,
                config=settings,
                **options,
            )
        shown = result
        if threshold is not None:
            shown = result.filter(min_level=threshold)
            note(diff_note(result.diff, shown.diff, threshold), quiet)
        _emit(shown, top, outputs.stdout)
        if out is not None and outputs.file is not None:
            write_report(shown, out, outputs.file, quiet, append)
    except LogfoldError as error:
        raise fail(error, debug) from None
    if not result.passed:
        raise typer.Exit(exit_codes.CHECK_FAILED)
