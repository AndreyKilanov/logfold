"""Warnings for flags that were given but had no effect on the run."""

from __future__ import annotations

from logfold.model import RunMetrics

_CHUNKED_ONLY = {
    "--warm-start": "starts every chunk from the tree of the first one",
    "--chunk-mb": "sets the size of the chunks",
}


def ignored_flag_warnings(metrics: RunMetrics, given: dict[str, bool]) -> list[str]:
    """Name the flags that only matter for the chunked strategy when the run was sequential.

    The strategy is known only after the run (``auto`` decides from the input), so the check is made on the metrics.
    On the python engine the library already logs a warning for ``--warm-start``, so it is not repeated here.

    Args:
        metrics: Execution facts of the finished run.
        given: For each flag name, whether the user passed it.

    Returns:
        One warning per flag that was given and ignored, in the order of ``given``.
    """
    if metrics.strategy != "sequential":
        return []
    reason = (
        "the python engine is always sequential"
        if metrics.engine == "python"
        else "use --strategy chunked to force chunks"
    )
    return [
        f"{flag} was ignored: it {_CHUNKED_ONLY[flag]}, but the run was sequential ({reason})"
        for flag, used in given.items()
        if used and flag in _CHUNKED_ONLY and not (metrics.engine == "python" and flag == "--warm-start")
    ]
