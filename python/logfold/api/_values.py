"""Giving the templates of an analysis the distributions of their values."""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence

from logfold.config import ExamplesMode
from logfold.ext.masks import Masker
from logfold.levels import severity
from logfold.model import Template
from logfold.model_values import TemplateValueChanges, ValueStats

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


def _shown_list(values: tuple[tuple[str, int], ...], mode: ExamplesMode, masker: Masker) -> tuple[tuple[str, int], ...]:
    """A list of new or gone values as the ``examples`` mode allows to show it."""
    if mode == "raw":
        return values
    if mode == "none":
        return ()
    summed: dict[str, int] = {}
    for value, count in values:
        hidden = masker.mask(value)
        summed[hidden] = summed.get(hidden, 0) + count
    return tuple(sorted(summed.items(), key=lambda pair: (-pair[1], pair[0])))


def finish_changes(
    changes: Sequence[TemplateValueChanges],
    levels: Mapping[str, str | None],
    mode: ExamplesMode,
    masker: Masker,
) -> tuple[TemplateValueChanges, ...]:
    """Give the templates of a comparison of values their level and show their values as ``examples`` allows.

    Args:
        changes: The templates whose values differ, from the engine.
        levels: The most severe level of each template in either run, by identifier.
        mode: The ``examples`` mode.
        masker: The masking rules of the runs, for the ``masked`` mode.

    Returns:
        The templates with ``level`` set, most frequent new value first within a position, ordered by text.
    """
    finished = []
    for item in changes:
        shown = tuple(
            dataclasses.replace(
                change, new=_shown_list(change.new, mode, masker), gone=_shown_list(change.gone, mode, masker)
            )
            for change in item.changes
        )
        finished.append(dataclasses.replace(item, level=levels.get(item.id), changes=shown))
    return tuple(finished)


def worst_levels(
    ids: Sequence[str], first: Sequence[str | None], second: Sequence[str | None]
) -> dict[str, str | None]:
    """The most severe level of every template over two runs, by identifier."""
    worst: dict[str, str | None] = {}
    for template, one, two in zip(ids, first, second, strict=True):
        worst[template] = max(one, two, key=severity)
    return worst
