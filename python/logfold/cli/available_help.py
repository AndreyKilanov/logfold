"""Help text that names the plugins available from the catalog next to the options that take a plugin name."""

from __future__ import annotations

from typing import Any

from typer.core import TyperCommand, TyperOption

from logfold.errors import LogfoldError

_KIND_OF_OPTION = {"format": "format", "report": "reporter", "matcher": "matcher"}
_BASE_HELP = "_logfold_base_help"
_MAX_NAMES = 6


def available_names(kind: str) -> list[str]:
    """Return the names of the catalog plugins of one kind that can be installed here.

    Args:
        kind: ``format``, ``reporter`` or ``matcher``.

    Returns:
        The names, sorted; empty when the catalog cannot be read or nothing fits this logfold.
    """
    from logfold.plugins import listing  # noqa: PLC0415 - slow imports

    try:
        rows = listing.list_plugins(kind=kind, status="available")
    except (LogfoldError, OSError):
        return []
    return sorted({row.name for row in rows if row.compatible})


class AvailableHelpCommand(TyperCommand):
    """A command whose ``--help`` adds "available to install" to the options that take a plugin name.

    The catalog is read only when the help is shown, so the other invocations pay nothing for it.
    """

    def format_help(self, ctx: Any, formatter: Any) -> None:
        """Add the available plugins to the help of ``--format``, ``--report`` and ``--matcher``, then print it.

        Args:
            ctx: The click context.
            formatter: The click help formatter.
        """
        for param in self.params:
            kind = _KIND_OF_OPTION.get(param.name or "")
            if kind is None or not isinstance(param, TyperOption):
                continue
            base = getattr(param, _BASE_HELP, param.help)
            setattr(param, _BASE_HELP, base)
            names = available_names(kind)
            shown = ", ".join(names[:_MAX_NAMES]) + (", ..." if len(names) > _MAX_NAMES else "")
            param.help = f"{base} Available to install: {shown} ('logfold plugins info NAME')." if names else base
        super().format_help(ctx, formatter)
