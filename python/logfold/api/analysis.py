"""``analyze()``: fold one run into templates."""

from __future__ import annotations

from collections.abc import Sequence

from logfold.api._common import (
    PathLike,
    Progress,
    _execution,
    _meta,
    _mine,
    _mining,
    _paths,
    _summary,
    _templates,
    _warnings,
)
from logfold.config import (
    ExamplesMode,
    ExecutionConfig,
    MaskRule,
    MiningConfig,
)
from logfold.ext.formats import Format, FormatSpec
from logfold.ext.masks import Masker
from logfold.formats import resolve_format
from logfold.model import (
    AnalysisResult,
)


def analyze(
    path: PathLike | Sequence[PathLike],
    *,
    format: str | FormatSpec | Format = "auto",
    multiline: bool | None = None,
    depth: int | None = None,
    sim_th: float | None = None,
    max_children: int | None = None,
    max_templates: int | None = None,
    masks: Sequence[MaskRule] | None = None,
    high_cardinality: bool = False,
    mining: MiningConfig | None = None,
    execution: ExecutionConfig | None = None,
    engine: str | None = None,
    strategy: str | None = None,
    threads: int | None = None,
    chunk_bytes: int | None = None,
    examples: ExamplesMode = "raw",
    progress: Progress | None = None,
) -> AnalysisResult:
    """Fold a log into templates.

    Args:
        path: One input file or several files that form a single run (``-`` is standard input).
        format: ``auto``, a registered name, ``regex:<pattern>``, a format specification or a ``Format`` object.
        multiline: Join continuation lines to the previous record; ``None`` keeps the format's default.
        depth: Tree depth (default 4, Drain3 convention).
        sim_th: Similarity threshold (default 0.4).
        max_children: Maximum children per tree node (default 100).
        max_templates: Maximum number of templates before pooling (default 100000).
        masks: Masking rules replacing the defaults.
        high_cardinality: Mode for data with a huge number of distinct message shapes (unstructured text, random ids):
            caps templates at 5000 unless ``max_templates`` is given, pools the rest into catch-all templates and
            runs sequentially. Much faster and bounded in memory; rare templates are not kept apart.
        mining: Full mining configuration; the keyword arguments above override its fields.
        execution: Full execution configuration; the keyword arguments below override its fields.
        engine: ``auto``, ``native`` or ``python``.
        strategy: ``auto``, ``sequential`` or ``chunked``.
        threads: Worker threads for the chunked strategy.
        chunk_bytes: Chunk size of the chunked strategy.
        examples: ``raw`` keeps example messages, ``masked`` applies the masking rules to them, ``none`` drops them.
        progress: Optional callback receiving consumed input byte counts.

    Returns:
        The templates, run counters, metrics and provenance.

    Raises:
        ConfigError: If an option is invalid.
        FormatError: If the format is invalid or cannot be detected.
        SourceError: If an input cannot be read.
        EngineError: If the requested engine is unavailable.
    """
    run = _paths(path, "analyze()")
    resolved = resolve_format(format, run, multiline)
    spec = resolved.spec
    mining_config = _mining(mining, depth, sim_th, max_children, max_templates, masks, high_cardinality)
    exec_config = _execution(execution, engine, strategy, threads, chunk_bytes, high_cardinality)
    mined, used = _mine((run,), spec, mining_config, exec_config, progress)
    summary = _summary(run, mined.runs[0])
    masker = Masker(mining_config.masks)
    templates = _templates(mined.templates, 0, summary.tz_aware, examples, masker)
    return AnalysisResult(
        templates=templates,
        run=summary,
        metrics=mined.metrics,
        meta=_meta(spec, mining_config, used),
        warnings=tuple(_warnings([summary], used, exec_config, resolved, mining_config, high_cardinality)),
    )
