"""Giving the templates of an analysis the distributions of their values."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping

from logfold.config import ExamplesMode
from logfold.ext.masks import Masker
from logfold.model import Template
from logfold.model_values import ValueStats

DEFAULT_VALUE_TEMPLATES = 200


def _shown(item: ValueStats, mode: ExamplesMode, masker: Masker) -> ValueStats:
    """The statistics as the ``examples`` mode allows to show them: raw, masked (and summed) or without the values."""
    if mode == "raw":
        return item
    if mode == "none":
        return dataclasses.replace(item, top=())
    summed: dict[str, int] = {}
    for value, count in item.top:
        hidden = masker.mask(value)
        summed[hidden] = summed.get(hidden, 0) + count
    ranked = sorted(summed.items(), key=lambda pair: (-pair[1], pair[0]))
    return dataclasses.replace(item, top=tuple(ranked))


def attach_values(
    templates: tuple[Template, ...],
    values: Mapping[str, tuple[tuple[ValueStats, ...], ...]] | None,
    mode: ExamplesMode,
    masker: Masker,
) -> tuple[Template, ...]:
    """Put the values of the tracked templates on them; the other templates keep ``values=None``.

    Args:
        templates: The templates of the run.
        values: The values by template identifier, one tuple per run, or ``None`` when none were asked for.
        mode: The ``examples`` mode: it decides whether the values may be shown as they are.
        masker: The masking rules of the run, for the ``masked`` mode.

    Returns:
        The templates, those that were tracked with their values.
    """
    if values is None:
        return templates
    attached = []
    for template in templates:
        runs = values.get(template.id)
        if runs is None:
            attached.append(template)
        else:
            attached.append(dataclasses.replace(template, values=tuple(_shown(item, mode, masker) for item in runs[0])))
    return tuple(attached)
