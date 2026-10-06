"""The hook through which the native engine offers to render the pipeline reports.

The reporters of :mod:`logfold.plugins` cannot import the engine (the layers are siblings), so the engine registers
its renderer here when it loads, and a reporter asks for it. Without a renderer, which is the case for the pure-Python
install, the reporter renders in Python.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Renderer = Callable[[str, dict[str, Any], dict[str, Any]], str]
"""``render(report, data, options)`` returns the text of a report; ``data`` holds the columns of a result."""

_renderer: Renderer | None = None


def set_renderer(renderer: Renderer | None) -> None:
    """Register the native renderer, or remove it with ``None``.

    Args:
        renderer: A function ``(report name, result columns, options) -> text``.
    """
    global _renderer  # noqa: PLW0603 - a module-level hook is the registry
    _renderer = renderer


def get_renderer() -> Renderer | None:
    """Return the native renderer, or ``None`` when there is none."""
    return _renderer
