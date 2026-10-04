"""Reporter extension point: turns a result object into text."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from logfold.model import AnalysisResult, DiffResult


@runtime_checkable
class Reporter(Protocol):
    """Renders results. Reporters see only the public result model, never the engine.

    Attributes:
        name: Reporter name used in ``result.render(name)`` and in the CLI ``--out`` suffix mapping.
        kinds: Result kinds the reporter supports: ``analysis`` and/or ``diff``.
    """

    name: str
    kinds: tuple[str, ...]

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result`` to text.

        Args:
            result: The result to render.
            **options: Reporter-specific options.

        Returns:
            The rendered document.
        """
        ...
