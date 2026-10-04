"""Self-contained HTML reporter.

The report is a single file with no network access. Log content is untrusted, so every dynamic value is escaped and a
strict Content-Security-Policy allows only the inline style and script whose SHA-256 hashes are embedded in the policy.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Sequence
from html import escape

from logfold.model import AnalysisResult, DiffEntry, DiffResult, RunSummary, Template

DEFAULT_LIMIT = 2000
_VARIABLE = re.compile(r"(<[A-Z]+>|<\*>)")

_CSS = """
:root{--bg:#f7f8fa;--fg:#1b1f24;--muted:#5b6570;--card:#fff;--line:#e2e6ea;--accent:#2563eb;--bar:#93b4f5;
--new:#15803d;--gone:#b45309;--chg:#7c3aed;--bad:#b91c1c;--var:#9a3412;--code:#f1f3f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1317;--fg:#e6e9ec;--muted:#98a2ad;--card:#171c22;--line:#2a323b;
--accent:#6ea0ff;--bar:#35538f;--new:#4ade80;--gone:#fbbf24;--chg:#c4a1ff;--bad:#f87171;--var:#fdba74;--code:#222a32}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 8px}.sub{color:var(--muted);margin:0 0 16px;overflow-wrap:anywhere}
.cards{display:flex;flex-wrap:wrap;gap:10px;margin:12px 0}.card{background:var(--card);border:1px solid var(--line);
border-radius:8px;padding:10px 14px;min-width:130px}.card b{display:block;font-size:20px}
.card span{color:var(--muted);font-size:12px}.warn{background:var(--card);border:1px solid var(--gone);
border-left-width:4px;border-radius:6px;padding:8px 12px;margin:8px 0}
input[type=search]{width:100%;max-width:420px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--fg);margin:8px 0}.wrap{overflow-x:auto;border:1px solid var(--line);
border-radius:8px;background:var(--card)}table{border-collapse:collapse;width:100%}
th,td{padding:6px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.t{font-family:ui-monospace,Consolas,monospace;font-size:13px;overflow-wrap:anywhere}.v{color:var(--var);font-weight:600}
.bar{display:inline-block;height:8px;background:var(--bar);border-radius:3px;vertical-align:middle;margin-right:6px}
.lvl{font-size:11px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--muted)}
.lvl.WARN{color:var(--gone);border-color:var(--gone)}.lvl.ERROR,.lvl.FATAL{color:var(--bad);border-color:var(--bad)}
details{margin-top:4px}summary{cursor:pointer;color:var(--muted);font-size:12px}
pre{margin:4px 0 0;padding:6px 8px;background:var(--code);border-radius:6px;white-space:pre-wrap;
overflow-wrap:anywhere;font-size:12px}.up{color:var(--bad)}.down{color:var(--new)}.empty{color:var(--muted);padding:12px}
"""

_JS = """
document.querySelectorAll('input[data-filter]').forEach(function(box){
  box.addEventListener('input',function(){
    var needle=box.value.toLowerCase();
    document.querySelectorAll(box.dataset.filter+' tbody tr').forEach(function(row){
      row.hidden=needle!==''&&row.dataset.text.indexOf(needle)===-1;
    });
  });
});
"""


def _sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii") + "'"


def _template_html(text: str) -> str:
    parts = _VARIABLE.split(text)
    return "".join(
        f'<span class="v">{escape(part)}</span>' if index % 2 else escape(part) for index, part in enumerate(parts)
    )


def _level_html(level: str | None) -> str:
    return f'<span class="lvl {escape(level)}">{escape(level)}</span>' if level else ""


def _example_html(example: str | None) -> str:
    if not example:
        return ""
    return f"<details><summary>example</summary><pre>{escape(example)}</pre></details>"


def _count(value: int) -> str:
    return f"{value:,}"


def _percent(value: float) -> str:
    if value == 0:
        return "0%"
    return f"{value:.2%}" if value < 0.1 else f"{value:.1%}"


def _card(label: str, value: str) -> str:
    return f'<div class="card"><b>{escape(value)}</b><span>{escape(label)}</span></div>'


def _warnings_html(warnings: Sequence[str]) -> str:
    return "".join(f'<div class="warn">{escape(text)}</div>' for text in warnings)


def _run_sub(*runs: RunSummary) -> str:
    return " &rarr; ".join(escape(run.name) for run in runs)


def _analysis_rows(templates: Sequence[Template], total: int) -> str:
    rows = []
    for rank, template in enumerate(templates, start=1):
        share = template.count / total if total else 0.0
        needle = f"{template.text} {template.example or ''}".lower()
        rows.append(
            f'<tr data-text="{escape(needle, quote=True)}"><td class="n">{rank}</td>'
            f'<td class="n">{_count(template.count)}</td>'
            f'<td class="n"><span class="bar" style="width:{max(1, round(share * 80))}px"></span>{_percent(share)}</td>'
            f"<td>{_level_html(template.level)}</td>"
            f'<td><div class="t">{_template_html(template.text)}</div>{_example_html(template.example)}</td></tr>'
        )
    return "".join(rows)


def _analysis_body(result: AnalysisResult, limit: int) -> str:
    shown = result.templates[:limit]
    run = result.run
    cards = "".join(
        [
            _card("records", _count(run.records)),
            _card("lines", _count(run.lines)),
            _card("templates", _count(len(result.templates))),
            _card("unparsed lines", _count(run.unparsed)),
            _card("format", result.meta.format),
            _card("engine", result.metrics.engine),
            _card("seconds", f"{result.metrics.wall_total_s:.2f}"),
        ]
    )
    note = ""
    if len(result.templates) > len(shown):
        note = (
            f'<div class="warn">Showing the {_count(len(shown))} most frequent '
            f"of {_count(len(result.templates))} templates.</div>"
        )
    table = (
        '<div class="wrap"><table id="templates"><thead><tr><th>#</th><th>count</th><th>share</th><th>level</th>'
        f"<th>template</th></tr></thead><tbody>{_analysis_rows(shown, run.records)}</tbody></table></div>"
        if shown
        else '<div class="empty">No templates.</div>'
    )
    return (
        f'<h1>logfold analysis</h1><p class="sub">{_run_sub(run)}</p><div class="cards">{cards}</div>'
        f'{_warnings_html(result.warnings)}{note}<input type="search" placeholder="Filter templates" '
        f'data-filter="#templates" aria-label="Filter templates">{table}'
    )


def _diff_rows(entries: Sequence[DiffEntry], kind: str) -> str:
    rows = []
    for entry in entries:
        needle = f"{entry.text} {entry.example or ''}".lower()
        if entry.ratio is None:
            change = "new" if kind == "new" else "gone"
        else:
            css = "up" if entry.ratio > 1 else "down"
            change = f'<span class="{css}">&times;{entry.ratio:.2f}</span>'
        rows.append(
            f'<tr data-text="{escape(needle, quote=True)}"><td class="n">{_count(entry.before_count)}</td>'
            f'<td class="n">{_count(entry.after_count)}</td>'
            f'<td class="n">{_percent(entry.before_share)} &rarr; {_percent(entry.after_share)}</td>'
            f'<td class="n">{change}</td><td>{_level_html(entry.level)}</td>'
            f'<td><div class="t">{_template_html(entry.text)}</div>{_example_html(entry.example)}</td></tr>'
        )
    return "".join(rows)


def _diff_section(title: str, entries: Sequence[DiffEntry], kind: str, limit: int, table_id: str) -> str:
    if not entries:
        return f'<h2>{escape(title)} (0)</h2><div class="empty">Nothing to report.</div>'
    shown = entries[:limit]
    note = ""
    if len(entries) > len(shown):
        note = f'<div class="warn">Showing {_count(len(shown))} of {_count(len(entries))}.</div>'
    return (
        f"<h2>{escape(title)} ({_count(len(entries))})</h2>{note}"
        f'<div class="wrap"><table id="{table_id}"><thead><tr><th>before</th><th>after</th><th>share</th>'
        f"<th>change</th><th>level</th><th>template</th></tr></thead>"
        f"<tbody>{_diff_rows(shown, kind)}</tbody></table></div>"
    )


def _diff_body(result: DiffResult, limit: int) -> str:
    cards = "".join(
        [
            _card("new", _count(len(result.new_templates))),
            _card("new WARN+", _count(len(result.new_alerts))),
            _card("disappeared", _count(len(result.disappeared))),
            _card("changed", _count(len(result.changed))),
            _card("unchanged", _count(result.unchanged)),
            _card("records before", _count(result.before.records)),
            _card("records after", _count(result.after.records)),
        ]
    )
    sections = "".join(
        [
            _diff_section("New templates", result.new_templates, "new", limit, "new"),
            _diff_section("Changed templates", result.changed, "changed", limit, "changed"),
            _diff_section("Disappeared templates", result.disappeared, "gone", limit, "gone"),
        ]
    )
    return (
        f'<h1>logfold diff</h1><p class="sub">{_run_sub(result.before, result.after)}</p>'
        f'<div class="cards">{cards}</div>'
        f'{_warnings_html(result.warnings)}<input type="search" placeholder="Filter templates" '
        f'data-filter="body" aria-label="Filter templates">{sections}'
    )


class HtmlReporter:
    """Renders results as one self-contained, script-light HTML document.

    Attributes:
        name: ``html``.
        kinds: Supports analysis and diff results.
    """

    name: str = "html"
    kinds: tuple[str, ...] = ("analysis", "diff")

    def render(self, result: AnalysisResult | DiffResult, **options: object) -> str:
        """Render ``result``.

        Args:
            result: Result to render.
            **options: ``limit`` (rows per table, default 2000).

        Returns:
            A complete HTML document.
        """
        raw_limit = options.get("limit", DEFAULT_LIMIT)
        limit = raw_limit if isinstance(raw_limit, int) and raw_limit > 0 else DEFAULT_LIMIT
        if isinstance(result, DiffResult):
            body = _diff_body(result, limit)
            title = "logfold diff"
        else:
            body = _analysis_body(result, limit)
            title = "logfold analysis"
        policy = (
            f"default-src 'none'; style-src {_sha(_CSS)}; script-src {_sha(_JS)}; base-uri 'none'; form-action 'none'"
        )
        return (
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta http-equiv="Content-Security-Policy" content="{escape(policy, quote=True)}">'
            f"<title>{escape(title)}</title><style>{_CSS}</style></head><body><main>{body}</main>"
            f"<script>{_JS}</script></body></html>\n"
        )
