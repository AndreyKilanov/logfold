"""Display names for temporary input files, so that results show ``docker:web`` and not a path in a temp folder."""

from __future__ import annotations

_labels: dict[str, str] = {}


def set_label(path: str, label: str) -> None:
    """Show ``label`` wherever ``path`` would be shown in a result.

    Args:
        path: The path of a temporary file.
        label: What to show instead.
    """
    _labels[path] = label


def clear_label(path: str) -> None:
    """Forget the label of ``path``.

    Args:
        path: The path given to :func:`set_label`.
    """
    _labels.pop(path, None)


def label_of(path: str) -> str:
    """Return the label of ``path``, or ``path`` itself when it has none.

    Args:
        path: An input path.

    Returns:
        The text to show.
    """
    return _labels.get(path, path)
