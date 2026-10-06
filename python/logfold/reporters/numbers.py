"""Number formatting shared by the built-in reports and the command line."""

from __future__ import annotations

__all__ = ["format_p_value"]


def format_p_value(p_value: float | None) -> str:
    """Format a p-value for people.

    Args:
        p_value: The p-value, or ``None``.

    Returns:
        An empty string for ``None``, ``<0.001`` for small values, otherwise three decimals.
    """
    if p_value is None:
        return ""
    return "<0.001" if p_value < 0.001 else f"{p_value:.3f}"
