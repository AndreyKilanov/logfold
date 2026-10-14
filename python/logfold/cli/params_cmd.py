"""The ``logfold params`` command: the values that one message gives to the variable parts of a template."""

from __future__ import annotations

import json
from typing import Annotated

import typer

import logfold
from logfold.cli.options import AsJson, Debug, Delimiters, Masks, MasksFile, NoMasks, read_delimiters, read_masks
from logfold.cli.runtime import config_note, fail, settings_of, write_stdout
from logfold.errors import ConfigError, LogfoldError
from logfold.ext.text import printable

EXAMPLES = """Examples:

  logfold params "user <NUM> logged in from <IP>" "user 42 logged in from 10.0.0.1:8080"

  logfold params "login failed for <*>" "login failed for alice" --json"""


def params(
    ctx: typer.Context,
    template: Annotated[str, typer.Argument(help="Text of a template, as a report shows it.")],
    message: Annotated[str, typer.Argument(help="One record, as written in the log.")],
    no_masks: NoMasks = False,
    masks: Masks = None,
    masks_file: MasksFile = None,
    delimiters: Delimiters = None,
    as_json: AsJson = False,
    debug: Debug = False,
) -> None:
    """Print the values that MESSAGE has at the variable parts of TEMPLATE: position, rule name or '*', and value."""
    try:
        settings = settings_of(ctx)
        config_note(settings, True)
        found = logfold.extract_parameters(
            template,
            message,
            masks=read_masks(no_masks, masks, masks_file),
            config=settings,
            delimiters=read_delimiters(delimiters),
        )
        if found is None:
            raise ConfigError(
                "the message does not fit the template",
                hint="it needs the same number of tokens and the same constant tokens; use the masks that the template "
                "was mined with (--no-masks, a logfold.toml)",
            )
        if as_json:
            rows = [{"position": p.position, "name": p.name, "value": p.value} for p in found]
            write_stdout(json.dumps({"parameters": rows}, ensure_ascii=False) + "\n")
        else:
            write_stdout("".join(f"{p.position}\t{p.name}\t{printable(p.value)}\n" for p in found))
    except LogfoldError as error:
        raise fail(error, debug) from None
