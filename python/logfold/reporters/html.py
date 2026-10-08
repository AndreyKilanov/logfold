"""Self-contained HTML reporter.

The report is a single file with no network access. Log content is untrusted, so every dynamic value is escaped and a
strict Content-Security-Policy allows only the inline style and script whose SHA-256 hashes are embedded in the policy.
"""

from __future__ import annotations

import base64
import hashlib
import re
from collections.abc import Sequence
from html import escape as _escape

from logfold.ext.text import printable
from logfold.model import AnalysisResult, DiffEntry, DiffResult, RunMetrics, RunSummary, Template
from logfold.reporters.numbers import format_p_value

DEFAULT_LIMIT = 2000
_ALERT_LEVELS = ("WARN", "ERROR", "FATAL")
_VARIABLE = re.compile(r"(<[A-Z]+>|<\*>)")

_BAR_MAX = 80
_CSS = """
:root{--bg:#f7f8fa;--fg:#1b1f24;--muted:#5b6570;--card:#fff;--line:#e2e6ea;--accent:#2563eb;--bar:#93b4f5;
--new:#15803d;--gone:#b45309;--chg:#7c3aed;--bad:#b91c1c;--var:#9a3412;--code:#f1f3f5}
@media (prefers-color-scheme:dark){:root{--bg:#0f1317;--fg:#e6e9ec;--muted:#98a2ad;--card:#171c22;--line:#2a323b;
--accent:#6ea0ff;--bar:#35538f;--new:#4ade80;--gone:#fbbf24;--chg:#c4a1ff;--bad:#f87171;--var:#fdba74;--code:#222a32}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:24px 16px 64px}h1{font-size:22px;margin:0 0 4px}
h2{font-size:17px;margin:28px 0 8px}.sub{color:var(--muted);margin:0 0 16px;overflow-wrap:anywhere}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}
.cards.c5{grid-template-columns:repeat(5,minmax(0,1fr))}
@media (max-width:760px){.cards.c5{grid-template-columns:repeat(2,minmax(0,1fr))}}
.card{background:var(--card);border:1px solid var(--line);border-top:3px solid var(--line);border-radius:8px;
padding:10px 14px}.card b{display:block;font-size:22px;font-variant-numeric:tabular-nums}
.card.new{border-top-color:var(--new)}.card.new b{color:var(--new)}.card.alert{border-top-color:var(--bad)}
.card.alert b{color:var(--bad)}.card.gone{border-top-color:var(--gone)}.card.gone b{color:var(--gone)}
.card.chg{border-top-color:var(--chg)}.card.chg b{color:var(--chg)}
.card.info{border-top-color:var(--accent)}.card.info b{color:var(--accent)}
.card span{color:var(--muted);font-size:12px}.warn{background:var(--card);border:1px solid var(--gone);
border-left-width:4px;border-radius:6px;padding:8px 12px;margin:8px 0}
input[type=search]{width:100%;max-width:420px;padding:7px 10px;border:1px solid var(--line);border-radius:6px;
background:var(--card);color:var(--fg);margin:8px 0}.wrap{overflow-x:auto;border:1px solid var(--line);
border-radius:8px;background:var(--card)}table{border-collapse:collapse;width:100%}
table.fx{table-layout:fixed;min-width:760px}.wi{width:60px}.wn{width:90px}.ws{width:190px}.wl{width:100px}
th,td{padding:6px 10px;text-align:left;vertical-align:top;border-bottom:1px solid var(--line)}
th{font-size:12px;color:var(--muted);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
th.n,td.n{text-align:right}td.n{font-variant-numeric:tabular-nums;white-space:nowrap}
.t{font-family:ui-monospace,Consolas,monospace;font-size:13px;overflow-wrap:anywhere}.v{color:var(--var);font-weight:600}
.track{display:inline-block;width:80px;margin-right:8px;vertical-align:middle;text-align:left}
.bar{display:inline-block;height:8px;background:var(--bar);border-radius:3px;vertical-align:middle}
.pct{display:inline-block;min-width:54px;text-align:right}
.lvl{font-size:11px;padding:1px 6px;border-radius:9px;border:1px solid var(--line);color:var(--muted)}
.lvl.WARN{color:var(--gone);border-color:var(--gone)}.lvl.ERROR,.lvl.FATAL{color:var(--bad);border-color:var(--bad)}
details{margin-top:4px}summary{cursor:pointer;color:var(--muted);font-size:12px}
pre{margin:4px 0 0;padding:6px 8px;background:var(--code);border-radius:6px;white-space:pre-wrap;
overflow-wrap:anywhere;font-size:12px}.up{color:var(--bad)}.down{color:var(--new)}.empty{color:var(--muted);padding:12px}
"""
_CSS += "".join(f".bw{width}{{width:{width}px}}" for width in range(1, _BAR_MAX + 1))

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


def _head(*columns: tuple[str, bool]) -> str:
    """Build a table head; numeric columns get a right-aligned header that sits above their right-aligned cells."""
    cells = "".join(f'<th class="n">{name}</th>' if numeric else f"<th>{name}</th>" for name, numeric in columns)
    return f"<thead><tr>{cells}</tr></thead>"


_ANALYSIS_COLS = '<colgroup><col class="wi"><col class="wn"><col class="ws"><col class="wl"><col></colgroup>'
_ANALYSIS_HEAD = _head(("#", True), ("count", True), ("share", True), ("level", False), ("template", False))
_DIFF_COLS = (
    '<colgroup><col class="wn"><col class="wn"><col class="ws"><col class="wn"><col class="wl"><col></colgroup>'
)
_DIFF_HEAD = _head(
    ("before", True), ("after", True), ("share", True), ("change", True), ("level", False), ("template", False)
)


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


def escape(text: str, quote: bool = True) -> str:
    """HTML-escape a value; control characters are shown as visible hex escapes, as in the text reports."""
    return _escape(printable(text), quote=quote)


def _count(value: int) -> str:
    return f"{value:,}"


def _percent(value: float) -> str:
    if value == 0:
        return "0%"
    return f"{value:.2%}" if value < 0.1 else f"{value:.1%}"


def _card(label: str, value: str, tone: str = "") -> str:
    css = f"card {tone}" if tone else "card"
    return f'<div class="{css}"><b>{escape(value)}</b><span>{escape(label)}</span></div>'


def _count_card(label: str, count: int, tone: str) -> str:
    """A count card that takes its color only when there is something to look at."""
    return _card(label, _count(count), tone if count else "")


def _facts(data_format: str, metrics: RunMetrics, runs: tuple[RunSummary, RunSummary] | None = None) -> str:
    """The neutral row of facts under the counts: what was read and how it was run, five cards on every page."""
    if runs is None:
        cards = [
            _card("format", data_format),
            _card("engine", metrics.engine),
            _card("strategy", metrics.strategy),
            _card("threads", _count(metrics.threads)),
        ]
    else:
        cards = [
            _card("records before", _count(runs[0].records)),
            _card("records after", _count(runs[1].records)),
            _card("format", data_format),
            _card("engine", metrics.engine),
        ]
    return "".join([*cards, _card("seconds", f"{metrics.wall_total_s:.2f}")])


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
            f'<td class="n"><span class="track"><span class="bar bw{max(1, round(share * _BAR_MAX))}"></span></span>'
            f'<span class="pct">{_percent(share)}</span></td>'
            f"<td>{_level_html(template.level)}</td>"
            f'<td><div class="t">{_template_html(template.text)}</div>{_example_html(template.example)}</td></tr>'
        )
    return "".join(rows)


def _analysis_body(result: AnalysisResult, limit: int) -> str:
    shown = result.templates[:limit]
    run = result.run
    alerts = sum(1 for template in result.templates if template.level in _ALERT_LEVELS)
    counts = "".join(
        [
            _card("records", _count(run.records), "info"),
            _card("lines", _count(run.lines)),
            _card("templates", _count(len(result.templates)), "info"),
            _count_card("WARN+ templates", alerts, "alert"),
            _count_card("unparsed lines", run.unparsed, "gone"),
        ]
    )
    facts = _facts(result.meta.format, result.metrics)
    note = ""
    if len(result.templates) > len(shown):
        note = (
            f'<div class="warn">Showing the {_count(len(shown))} most frequent '
            f"of {_count(len(result.templates))} templates.</div>"
        )
    table = (
        f'<div class="wrap"><table id="templates" class="fx">{_ANALYSIS_COLS}{_ANALYSIS_HEAD}'
        f"<tbody>{_analysis_rows(shown, run.records)}</tbody></table></div>"
        if shown
        else '<div class="empty">Nothing to report.</div>'
    )
    return (
        f'<h1>logfold analysis</h1><p class="sub">{_run_sub(run)}</p>'
        f'<div class="cards c5">{counts}</div><div class="cards c5">{facts}</div>'
        f'{_warnings_html(result.warnings)}<input type="search" placeholder="Filter templates" '
        f'data-filter="#templates" aria-label="Filter templates">'
        f"<h2>Templates ({_count(len(result.templates))})</h2>{note}{table}"
    )


def _diff_rows(entries: Sequence[DiffEntry], kind: str) -> str:
    rows = []
    for entry in entries:
        needle = f"{entry.text} {entry.example or ''}".lower()
        if entry.ratio is None:
            change = "new" if kind == "new" else "gone"
        else:
            css = "up" if entry.ratio > 1 else "down"
            tip = ""
            if entry.score is not None:
                tip = f' title="{escape(f"score {entry.score:.1f}, p {format_p_value(entry.p_value)}")}"'
            change = f'<span class="{css}"{tip}>&times;{entry.ratio:.2f}</span>'
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
        f'<div class="wrap"><table id="{table_id}" class="fx">{_DIFF_COLS}{_DIFF_HEAD}'
        f"<tbody>{_diff_rows(shown, kind)}</tbody></table></div>"
    )


def _diff_body(result: DiffResult, limit: int) -> str:
    counts = "".join(
        [
            _count_card("new", len(result.new_templates), "new"),
            _count_card("new WARN+", len(result.new_alerts), "alert"),
            _count_card("disappeared", len(result.disappeared), "gone"),
            _count_card("changed", len(result.changed), "chg"),
            _card("unchanged", _count(result.unchanged)),
        ]
    )
    facts = _facts(result.meta.format, result.metrics, (result.before, result.after))
    sections = "".join(
        [
            _diff_section("New templates", result.new_templates, "new", limit, "new"),
            _diff_section("Changed templates", result.changed, "changed", limit, "changed"),
            _diff_section("Disappeared templates", result.disappeared, "gone", limit, "gone"),
        ]
    )
    return (
        f'<h1>logfold diff</h1><p class="sub">{_run_sub(result.before, result.after)}</p>'
        f'<div class="cards c5">{counts}</div><div class="cards c5">{facts}</div>'
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
