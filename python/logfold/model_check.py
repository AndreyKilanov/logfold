"""The result of :func:`logfold.check`: what a log holds that a saved model does not know."""

from __future__ import annotations

import dataclasses
import os
from dataclasses import dataclass
from typing import Any, cast

from logfold.errors import ConfigError
from logfold.ext import registry
from logfold.ext.files import check_appendable, write_text
from logfold.model import DiffResult, Unmatched


@dataclass(frozen=True, slots=True)
class Finding:
    """One reason why a log does not match its model.

    Attributes:
        kind: ``unmatched`` (too large a share of the records fits no template of the model), ``new`` (templates that
            the model does not have) or ``empty`` (no record was parsed, so nothing was checked).
        message: A sentence that says what was found, for a person.
        value: What was found: the share of the unmatched records in percent, the number of new templates, or 0.
        threshold: The limit that ``value`` crossed (in percent for ``unmatched``), or ``None`` when there is none.
    """

    kind: str
    message: str
    value: float
    threshold: float | None = None


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The check of a log against a saved model.

    Attributes:
        findings: The reasons why the check failed; empty when it passed.
        unmatched: The records that fit no template of the model, counted by their length in tokens.
        diff: The log compared with the model: the model is the first run (its saved counts) and the log the second.
            ``new_templates`` are the templates that the unmatched records form, ``changed`` the templates of the model
            whose share moved significantly, ``disappeared`` is always empty (a log shorter than the model lacks many
            of its templates, which is not a finding).
        max_unmatched: The limit of the unmatched records in percent, or ``None`` when it was not checked.
        fail_on: ``new-alerts``, ``new`` or ``none``: which new templates are a finding.
    """

    findings: tuple[Finding, ...]
    unmatched: Unmatched
    diff: DiffResult
    max_unmatched: float | None
    fail_on: str

    @property
    def passed(self) -> bool:
        """``True`` when there is no finding."""
        return not self.findings

    @property
    def unmatched_share(self) -> float:
        """The share of the records that fit no template of the model, from 0 to 1 (0 without records)."""
        records = self.diff.after.records
        return self.unmatched.records / records if records else 0.0

    def filter(self, *, min_level: str | None = None) -> CheckResult:
        """Keep only the new and changed templates at or above a level in the report; the findings stay as they are.

        Args:
            min_level: Keep entries whose most severe level is at least this one (``TRACE`` to ``FATAL``, any case).

        Returns:
            A new result.

        Raises:
            ConfigError: If ``min_level`` is not a level name.
            NoLevelsError: If ``min_level`` is given, there are entries and none has a level.
        """
        return dataclasses.replace(self, diff=self.diff.filter(min_level=min_level))

    def render(self, reporter: str, **options: object) -> str:
        """Render with a registered reporter: ``json`` writes the check, any other reporter writes :attr:`diff`.

        Args:
            reporter: Reporter name, for example ``json`` or ``github-summary``.
            **options: Reporter options.

        Returns:
            The rendered text.
        """
        if reporter == "json":
            return str(cast(Any, registry.get_reporter("json")).render(self, **options))
        return self.diff.render(reporter, **options)

    def save(
        self, path: str | os.PathLike[str], reporter: str | None = None, *, append: bool = False, **options: object
    ) -> str:
        """Render with a reporter and write the text to a file; see :meth:`logfold.DiffResult.save`.

        Args:
            path: Destination file (UTF-8).
            reporter: Reporter name; when ``None`` the suffix of ``path`` selects it.
            append: Add the text to the end of the file instead of replacing it.
            **options: Reporter options.

        Returns:
            The rendered text.

        Raises:
            UnknownSuffixError: If no reporter is named and the suffix selects none.
            ConfigError: If the reporter is unknown or does not support this kind of result.
            OSError: If the file cannot be written.
        """
        name = reporter if reporter is not None else registry.reporter_for_suffix(path)
        if append:
            check_appendable(name)
        text = self.render(name, **options)
        if not isinstance(text, str):
            raise ConfigError(f"reporter {name!r} returned {type(text).__name__}, expected text")
        write_text(path, text, append)
        return text

    def to_json(self, path: str | os.PathLike[str] | None = None, **options: object) -> str:
        """Render as JSON and optionally write it to a file.

        Args:
            path: Destination file; nothing is written when ``None``.
            **options: Reporter options.

        Returns:
            The JSON text.
        """
        text = self.render("json", **options)
        if path is not None:
            write_text(path, text)
        return text
