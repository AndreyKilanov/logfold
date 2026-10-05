"""Loading of saved analysis results and the comparison of two of them.

``load_analysis`` reads a JSON report back into an :class:`~logfold.model.AnalysisResult`; ``diff_saved`` compares two
such results without reading any log (see :func:`logfold.diff`).
"""

from __future__ import annotations

import codecs
import dataclasses
import json
import os
import time
from typing import Any

from logfold.comparison import classify
from logfold.config import DiffConfig, ExamplesMode
from logfold.engines.base import RunStatsData, TemplateStats
from logfold.errors import ConfigError, SourceError
from logfold.ext import registry
from logfold.model import (
    LEVEL_NAMES,
    AnalysisResult,
    DiffResult,
    RunMetrics,
    Template,
    datetime_to_micros,
)
from logfold.reporters.payload import analysis_from_payload

PathLike = str | os.PathLike[str]
MAX_REPORT_BYTES = 256 << 20


def load_analysis(path: PathLike) -> AnalysisResult:
    """Load an analysis result saved as a JSON report (``AnalysisResult.to_json()`` or ``--out result.json``).

    Args:
        path: The JSON report (UTF-8, at most 256 MiB). It must hold every template, so it must not have been
            written with a ``limit``.

    Returns:
        The analysis result, ready for :func:`diff`.

    Raises:
        SourceError: If the file cannot be read or is not a complete analysis report of a supported version.
    """
    name = os.fspath(path)
    try:
        size = os.stat(path).st_size
        if size > MAX_REPORT_BYTES:
            raise SourceError(f"{name!r} is {size:,} bytes; a report larger than {MAX_REPORT_BYTES:,} bytes is refused")
        with open(path, "rb") as handle:
            raw = handle.read()
    except OSError as error:
        raise SourceError(f"cannot read an analysis report from {name!r}: {error}") from error
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        raise SourceError(
            f"{name!r} is UTF-16 text (a PowerShell 5 '>' redirect does that); write the report with --out instead"
        )
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, RecursionError) as error:
        raise SourceError(f"cannot read an analysis report from {name!r}: {error}") from error
    if not isinstance(payload, dict):
        raise SourceError(f"{name!r} is not an analysis report")
    return analysis_from_payload(payload)


MINING_ONLY_DEFAULTS: dict[str, Any] = {
    "format": "auto",
    "multiline": None,
    "recount": None,
    "depth": None,
    "sim_th": None,
    "max_children": None,
    "max_templates": None,
    "masks": None,
    "high_cardinality": False,
    "mining": None,
    "execution": None,
    "engine": None,
    "strategy": None,
    "threads": None,
    "chunk_bytes": None,
    "progress": None,
}


def _saved_stats(template: Template | None) -> RunStatsData:
    if template is None:
        return RunStatsData(0, None, None, (0,) * len(LEVEL_NAMES), None)
    return RunStatsData(
        count=template.count,
        first=datetime_to_micros(template.first_seen),
        last=datetime_to_micros(template.last_seen),
        levels=tuple(template.levels.get(name, 0) for name in LEVEL_NAMES),
        example=template.example,
    )


def _join_saved(before: AnalysisResult, after: AnalysisResult) -> list[TemplateStats]:
    first = {template.id: template for template in before.templates}
    second = {template.id: template for template in after.templates}
    joined: list[TemplateStats] = []
    for key in {**first, **second}:
        present = second.get(key) or first[key]
        runs = (_saved_stats(first.get(key)), _saved_stats(second.get(key)))
        joined.append(TemplateStats(id=present.id, text=present.text, runs=runs))
    return joined


def _saved_warnings(before: AnalysisResult, after: AnalysisResult) -> list[str]:
    warnings = [
        "saved results were mined separately and are not re-counted against a shared template tree; the same "
        "event may be reported as new and disappeared (try matcher='token_subset')"
    ]
    if before.meta.config_hash != after.meta.config_hash:
        warnings.append(
            f"the results were mined with different masks or parameters ({before.meta.config_hash} and "
            f"{after.meta.config_hash}); their templates may not be comparable"
        )
    if before.meta.format != after.meta.format:
        warnings.append(f"the results use different formats ({before.meta.format!r} and {after.meta.format!r})")
    for summary in (before.run, after.run):
        if summary.overflowed:
            warnings.append(
                f"{summary.name}: max_templates was reached; extra records were pooled into catch-all templates"
            )
        if summary.records == 0:
            warnings.append(f"{summary.name}: no records were parsed")
    return warnings


def diff_saved(before: AnalysisResult, after: AnalysisResult, config: DiffConfig, examples: ExamplesMode) -> DiffResult:
    """Compare two analysis results without reading any log.

    Args:
        before: Result of the first run.
        after: Result of the second run.
        config: Comparison parameters; ``recount`` is reported as off because nothing is recounted.
        examples: ``none`` drops the saved examples; ``masked`` is refused, the masking rules are not saved.

    Returns:
        The comparison, with a warning that the results were mined separately.

    Raises:
        ConfigError: If ``examples`` is ``masked`` or the results come from different algorithm versions.
    """
    started = time.perf_counter()
    if examples == "masked":
        raise ConfigError(
            "examples='masked' cannot be applied to saved analysis results (the masking rules are not saved); "
            "use 'none', or analyze the logs with examples='masked' before saving"
        )
    if before.meta.algo_version != after.meta.algo_version:
        raise ConfigError(
            f"the results come from different algorithm versions ({before.meta.algo_version} and "
            f"{after.meta.algo_version}) and cannot be compared; analyze both logs again"
        )
    config = dataclasses.replace(config, recount=False)
    classification = classify(
        _join_saved(before, after), before.run, after.run, config, registry.get_matcher(config.matcher)
    )
    new, gone, moved = classification.new, classification.disappeared, classification.changed
    if examples == "none":
        new = tuple(dataclasses.replace(e, example=None) for e in new)
        gone = tuple(dataclasses.replace(e, example=None) for e in gone)
        moved = tuple(dataclasses.replace(e, example=None) for e in moved)
    metrics = RunMetrics(
        engine=after.metrics.engine,
        strategy="sequential",
        threads=1,
        chunks=0,
        wall_total_s=time.perf_counter() - started,
        wall_mine_s=0.0,
        wall_merge_s=0.0,
        wall_recount_s=0.0,
        wall_freeze_s=0.0,
    )
    return DiffResult(
        new_templates=new,
        disappeared=gone,
        changed=moved,
        unchanged=classification.unchanged,
        before=before.run,
        after=after.run,
        config=config,
        metrics=metrics,
        meta=dataclasses.replace(after.meta, degraded=before.meta.degraded or after.meta.degraded),
        warnings=tuple(_saved_warnings(before, after)),
    )
