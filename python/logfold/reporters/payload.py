"""JSON-compatible payloads of results; the single definition of the public JSON schema (version 1)."""

from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import datetime
from typing import Any

from logfold.errors import SourceError
from logfold.model import (
    SCHEMA_VERSION,
    AnalysisResult,
    DiffEntry,
    DiffResult,
    ResultMeta,
    RunMetrics,
    RunSummary,
    Template,
    Unmatched,
)
from logfold.model_check import CheckResult
from logfold.model_values import NumericSummary, TemplateValueChanges, ValueStats


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def run_payload(run: RunSummary) -> dict[str, Any]:
    """Return the JSON form of a run summary.

    Args:
        run: Run summary.

    Returns:
        A JSON-compatible dictionary.
    """
    data = asdict(run)
    if run.unmatched is None:
        del data["unmatched"]
    if not run.evicted:
        del data["evicted"]
    data["unparsed_ratio"] = round(run.unparsed_ratio, 6)
    return data


def value_payload(item: ValueStats) -> dict[str, Any]:
    """Return the JSON form of the values of a position.

    Args:
        item: The statistics of a position.

    Returns:
        A JSON-compatible dictionary.
    """
    return {
        "position": item.position,
        "name": item.name,
        "count": item.count,
        "top": [{"value": value, "count": count} for value, count in item.top],
        "distinct": item.distinct,
        "capped": item.capped,
        "other": item.other,
        "numeric": None if item.numeric is None else asdict(item.numeric),
    }


def template_payload(template: Template, total_records: int) -> dict[str, Any]:
    """Return the JSON form of a template.

    Args:
        template: Template.
        total_records: Records of the run, used for the share.

    Returns:
        A JSON-compatible dictionary.
    """
    data: dict[str, Any] = {
        "id": template.id,
        "text": template.text,
        "count": template.count,
        "share": template.count / total_records if total_records else 0.0,
        "first_seen": _iso(template.first_seen),
        "last_seen": _iso(template.last_seen),
        "level": template.level,
        "levels": dict(template.levels),
        "example": template.example,
    }
    if template.values is not None:
        data["values"] = [value_payload(item) for item in template.values]
    return data


def entry_payload(entry: DiffEntry) -> dict[str, Any]:
    """Return the JSON form of a diff entry.

    Args:
        entry: Diff entry.

    Returns:
        A JSON-compatible dictionary.
    """
    return {
        "id": entry.id,
        "text": entry.text,
        "before_count": entry.before_count,
        "after_count": entry.after_count,
        "before_share": entry.before_share,
        "after_share": entry.after_share,
        "ratio": entry.ratio,
        "level": entry.level,
        "levels": dict(entry.levels),
        "example": entry.example,
        "first_seen": _iso(entry.first_seen),
        "last_seen": _iso(entry.last_seen),
        "score": entry.score,
        "p_value": entry.p_value,
    }


def analysis_payload(result: AnalysisResult, limit: int | None = None) -> dict[str, Any]:
    """Return the JSON form of an analysis result.

    Args:
        result: Analysis result.
        limit: Keep only the most frequent ``limit`` templates; ``None`` keeps all.

    Returns:
        A JSON-compatible dictionary with ``schema_version`` and ``kind == "analysis"``.
    """
    shown = result.templates if limit is None else result.templates[:limit]
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "analysis",
        "meta": asdict(result.meta),
        "run": run_payload(result.run),
        "metrics": asdict(result.metrics),
        "warnings": list(result.warnings),
        "template_count": len(result.templates),
        "templates": [template_payload(t, result.run.records) for t in shown],
    }


def changes_payload(changes: tuple[TemplateValueChanges, ...], limit: int | None = None) -> list[dict[str, Any]]:
    """Return the JSON form of the new and gone values of a diff.

    Args:
        changes: The templates whose values differ.
        limit: Keep only the first ``limit`` templates; ``None`` keeps all.

    Returns:
        A list with one item per template: ``id``, ``text``, ``level`` and ``positions``.
    """
    shown = changes if limit is None else changes[:limit]
    return [
        {
            "id": item.id,
            "text": item.text,
            "level": item.level,
            "positions": [
                {
                    "position": change.position,
                    "name": change.name,
                    "new": [{"value": value, "count": count} for value, count in change.new],
                    "gone": [{"value": value, "count": count} for value, count in change.gone],
                    "new_distinct": change.new_distinct,
                    "gone_distinct": change.gone_distinct,
                    "shared_distinct": change.shared_distinct,
                    "before_distinct": change.before_distinct,
                    "after_distinct": change.after_distinct,
                    "capped": change.capped,
                }
                for change in item.changes
            ],
        }
        for item in shown
    ]


def diff_payload(result: DiffResult, limit: int | None = None) -> dict[str, Any]:
    """Return the JSON form of a diff result.

    Args:
        result: Diff result.
        limit: Keep only the first ``limit`` entries of each category; ``None`` keeps all.

    Returns:
        A JSON-compatible dictionary with ``schema_version`` and ``kind == "diff"``.
    """

    def entries(items: tuple[DiffEntry, ...]) -> list[dict[str, Any]]:
        shown = items if limit is None else items[:limit]
        return [entry_payload(entry) for entry in shown]

    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "diff",
        "meta": asdict(result.meta),
        "before": run_payload(result.before),
        "after": run_payload(result.after),
        "config": asdict(result.config),
        "metrics": asdict(result.metrics),
        "warnings": list(result.warnings),
        "summary": {
            "new": len(result.new_templates),
            "new_alerts": len(result.new_alerts),
            "disappeared": len(result.disappeared),
            "changed": len(result.changed),
            "unchanged": result.unchanged,
        },
        "new_templates": entries(result.new_templates),
        "disappeared": entries(result.disappeared),
        "changed": entries(result.changed),
    }
    if result.value_changes is not None:
        payload["value_changes"] = changes_payload(result.value_changes, limit)
    return payload


def check_payload(result: CheckResult, limit: int | None = None) -> dict[str, Any]:
    """Return the JSON form of a check result.

    Args:
        result: Check result.
        limit: Keep only the first ``limit`` entries of each category of the comparison; ``None`` keeps all.

    Returns:
        A JSON-compatible dictionary with ``schema_version`` and ``kind == "check"``; ``diff`` is the diff payload.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "check",
        "passed": result.passed,
        "fail_on": result.fail_on,
        "max_unmatched": result.max_unmatched,
        "unmatched": {
            "records": result.unmatched.records,
            "share": round(result.unmatched_share, 6),
            "by_length": [list(pair) for pair in result.unmatched.by_length],
        },
        "findings": [asdict(finding) for finding in result.findings],
        "diff": diff_payload(result.diff, limit),
    }


def _moment(value: object) -> datetime | None:
    return datetime.fromisoformat(value) if isinstance(value, str) else None


def _value_stats(item: dict[str, Any]) -> ValueStats:
    numeric = item["numeric"]
    return ValueStats(
        position=int(item["position"]),
        name=str(item["name"]),
        count=int(item["count"]),
        top=tuple((str(entry["value"]), int(entry["count"])) for entry in item["top"]),
        distinct=int(item["distinct"]),
        capped=bool(item["capped"]),
        other=int(item["other"]),
        numeric=None if numeric is None else NumericSummary(**{key: numeric[key] for key in NumericSummary.__slots__}),
    )


def _template(data: dict[str, Any]) -> Template:
    text = str(data["text"])
    template_id = str(data["id"])
    if template_id != hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]:
        raise ValueError(f"template id {template_id!r} does not match its text")
    return Template(
        id=template_id,
        text=text,
        count=int(data["count"]),
        first_seen=_moment(data["first_seen"]),
        last_seen=_moment(data["last_seen"]),
        example=data["example"],
        level=data["level"],
        levels={str(name): int(count) for name, count in data["levels"].items()},
        values=None if "values" not in data else tuple(_value_stats(item) for item in data["values"]),
    )


def analysis_from_payload(payload: dict[str, Any]) -> AnalysisResult:
    """Rebuild an analysis result from its JSON form; the inverse of :func:`analysis_payload`.

    Args:
        payload: Parsed JSON of an analysis report.

    Returns:
        The analysis result. ``Template.example`` is whatever the report contained.

    Raises:
        SourceError: If the payload is not a complete analysis report of a supported schema version.
    """
    if payload.get("kind") != "analysis":
        raise SourceError(f"expected an analysis report, found kind {payload.get('kind')!r}")
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise SourceError(f"unsupported report schema version {payload.get('schema_version')!r}")
    try:
        templates = tuple(_template(item) for item in payload["templates"])
        run = {key: value for key, value in payload["run"].items() if key != "unparsed_ratio"}
        if run.get("unmatched") is not None:
            raw = run["unmatched"]
            run["unmatched"] = Unmatched(
                records=int(raw["records"]),
                by_length=tuple((int(length), int(count)) for length, count in raw["by_length"]),
            )
        result = AnalysisResult(
            templates=templates,
            run=RunSummary(**run),
            metrics=RunMetrics(**payload["metrics"]),
            meta=ResultMeta(**payload["meta"]),
            warnings=tuple(str(item) for item in payload["warnings"]),
        )
        expected = int(payload["template_count"])
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as error:
        raise SourceError(f"malformed analysis report: {error!r}") from error
    if len({template.id for template in templates}) != len(templates):
        raise SourceError("malformed analysis report: duplicate template ids")
    if expected != len(templates):
        raise SourceError(
            f"the report holds {len(templates)} of {expected} templates (it was written with a limit); "
            "save the full report"
        )
    return result
