"""Eval harness: runs a system over a dataset, scores it, writes reports."""
from __future__ import annotations

import html
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from ..core import Nl2Sql
from ..types import EvalCase, EvalCaseResult, EvalReport
from .matching import FlexibleMatcher


def _classify_failure(result, diff: Optional[str]) -> Optional[str]:
    if result.sql is None:
        return "no_sql"
    if result.stopped_reason == "tool_error":
        return "tool_error"
    if result.stopped_reason == "llm_error":
        return "tool_error"
    if result.stopped_reason == "max_iterations":
        return "schema"
    return "business_logic"


def run_eval(
    *,
    dataset: Iterable[EvalCase],
    system: Nl2Sql,
    matcher: Optional[FlexibleMatcher] = None,
    parallel: int = 1,
    repeat: int = 1,
    on_progress=None,
) -> EvalReport:
    matcher = matcher or FlexibleMatcher()
    cases = list(dataset)
    report = EvalReport()

    def _run_one(case: EvalCase) -> EvalCaseResult:
        t0 = time.monotonic()
        last_result = None
        for _ in range(max(1, repeat)):
            last_result = system.ask(case.question)
        elapsed = time.monotonic() - t0
        result = last_result

        passed = False
        diff: Optional[str] = None
        if case.expected_rows is not None:
            ok, diff = matcher.rows_match(result.rows, case.expected_rows)
            passed = ok
        elif case.expected_sql is not None:
            if result.sql:
                a = " ".join(result.sql.lower().split())
                b = " ".join(case.expected_sql.lower().split())
                passed = a == b
                if not passed:
                    diff = f"sql differs:\n  predicted: {a}\n  expected:  {b}"
        else:
            passed = result.sql is not None

        failure_category = None if passed else _classify_failure(result, diff)
        return EvalCaseResult(
            case_id=case.id,
            question=case.question,
            predicted_sql=result.sql,
            predicted_rows=result.rows,
            expected_rows=case.expected_rows,
            passed=passed,
            failure_category=failure_category,
            diff=diff,
            elapsed_s=elapsed,
            iterations=result.iterations,
        )

    if parallel and parallel > 1:
        with ThreadPoolExecutor(max_workers=parallel) as ex:
            for i, cr in enumerate(ex.map(_run_one, cases)):
                report.cases.append(cr)
                if on_progress:
                    on_progress(i + 1, len(cases), cr)
    else:
        for i, case in enumerate(cases):
            cr = _run_one(case)
            report.cases.append(cr)
            if on_progress:
                on_progress(i + 1, len(cases), cr)

    report.finished_at = datetime.now(timezone.utc)
    return report


def _esc(s) -> str:
    if s is None:
        return ""
    return html.escape(str(s))


_HTML_CSS = """
  :root {
    --bg: #ffffff; --fg: #0f172a; --muted: #475569;
    --accent: #1d4ed8; --pass: #166534; --pass-bg: #dcfce7;
    --fail: #991b1b; --fail-bg: #fee2e2;
    --border: #e2e8f0; --code-bg: #f8fafc;
  }
  [data-theme="dark"] {
    --bg: #0b1020; --fg: #e2e8f0; --muted: #94a3b8;
    --accent: #93c5fd; --pass: #86efac; --pass-bg: #052e16;
    --fail: #fca5a5; --fail-bg: #450a0a;
    --border: #1e293b; --code-bg: #0f172a;
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
    background: var(--bg); color: var(--fg);
    margin: 0; padding: 0; line-height: 1.55;
  }
  header {
    padding: 32px 40px 16px; border-bottom: 1px solid var(--border);
    display: flex; justify-content: space-between; align-items: baseline; gap: 16px;
    flex-wrap: wrap;
  }
  h1 { margin: 0; font-size: 1.6rem; font-weight: 600; }
  .meta { color: var(--muted); font-size: 0.95rem; }
  main { padding: 24px 40px 64px; max-width: 1280px; margin: 0 auto; }
  .summary {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px; margin-bottom: 32px;
  }
  .card {
    border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px;
    background: var(--bg);
  }
  .card .label { color: var(--muted); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.04em; }
  .card .value { font-size: 1.8rem; font-weight: 600; margin-top: 4px; }
  .card.accuracy .value { color: var(--accent); }
  table {
    width: 100%; border-collapse: collapse; font-size: 0.95rem;
    border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
  }
  th, td { text-align: left; padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: top; }
  th { background: var(--code-bg); font-weight: 600; }
  tr.detail-row td { background: var(--code-bg); padding: 0 16px 16px; }
  details summary { cursor: pointer; padding: 8px 0; color: var(--accent); }
  pre { background: var(--code-bg); padding: 12px 14px; border-radius: 8px; overflow-x: auto; font-size: 0.85rem; border: 1px solid var(--border); }
  code { font-family: "JetBrains Mono", "SF Mono", ui-monospace, monospace; }
  .pill { display: inline-block; padding: 2px 10px; border-radius: 9999px; font-size: 0.8rem; font-weight: 600; }
  .pill.pass { background: var(--pass-bg); color: var(--pass); }
  .pill.fail { background: var(--fail-bg); color: var(--fail); }
  .controls { display: flex; gap: 8px; align-items: center; }
  button { background: var(--bg); color: var(--fg); border: 1px solid var(--border); border-radius: 8px; padding: 6px 12px; cursor: pointer; font-size: 0.9rem; }
  button:hover { border-color: var(--accent); }
  ul.fails { margin: 8px 0; padding-left: 20px; }
  @media print {
    body { background: white; color: black; }
    button { display: none; }
    tr.detail-row td { background: #f7f7f7; }
    pre { font-size: 0.7rem; page-break-inside: avoid; }
    tr { page-break-inside: avoid; }
    header { padding: 0 0 12px; }
    main { padding: 12px 0; }
  }
"""

_HTML_SCRIPT = """
(function() {
  var key = "nl2sql-report-theme";
  var saved = localStorage.getItem(key);
  if (saved) document.documentElement.setAttribute("data-theme", saved);
  document.getElementById("theme-toggle").addEventListener("click", function() {
    var cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
    localStorage.setItem(key, cur);
  });
})();
"""


def _render_html_report(report: EvalReport, path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    accuracy_pct = f"{report.accuracy * 100:.1f}"
    fail_buckets = {}
    for c in report.failures:
        fail_buckets[c.failure_category or "unknown"] = (
            fail_buckets.get(c.failure_category or "unknown", 0) + 1
        )

    rows_html = []
    for c in report.cases:
        status = "pass" if c.passed else "fail"
        rows_html.append(
            f'<tr class="case {status}">'
            f'<td class="id">{_esc(c.case_id)}</td>'
            f'<td class="status"><span class="pill {status}">{status}</span></td>'
            f'<td class="cat">{_esc(c.failure_category or "")}</td>'
            f'<td class="q">{_esc(c.question)}</td>'
            f'<td class="iter">{c.iterations}</td>'
            f'<td class="elapsed">{c.elapsed_s:.2f}s</td>'
            f'</tr>'
        )
        diff_html = (
            f'<h4>Diff</h4><pre>{_esc(c.diff)}</pre>' if c.diff else ""
        )
        rows_html.append(
            f'<tr class="detail-row {status}"><td colspan="6">'
            f'<details><summary>Trace</summary>'
            f'<h4>Predicted SQL</h4>'
            f'<pre><code>{_esc(c.predicted_sql or "")}</code></pre>'
            f'{diff_html}'
            f'<h4>Predicted rows</h4>'
            f'<pre><code>{_esc(json.dumps(c.predicted_rows, indent=2, default=str)[:8000])}</code></pre>'
            f'<h4>Expected rows</h4>'
            f'<pre><code>{_esc(json.dumps(c.expected_rows, indent=2, default=str)[:8000])}</code></pre>'
            f'</details></td></tr>'
        )

    failures_summary = "".join(
        f"<li><strong>{_esc(k)}</strong>: {v}</li>" for k, v in fail_buckets.items()
    )
    failures_section = (
        f'<h2>Failure breakdown</h2><ul class="fails">{failures_summary}</ul>'
        if fail_buckets else ""
    )
    started = report.started_at.isoformat() if report.started_at else ""
    finished = report.finished_at.isoformat() if report.finished_at else ""

    html_doc = (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<title>nl2sql eval report</title>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<style>{_HTML_CSS}</style>\n'
        '</head>\n<body>\n'
        f'<header><div><h1>nl2sql evaluation report</h1>'
        f'<div class="meta">Started {started} | Finished {finished}</div></div>'
        '<div class="controls">'
        '<button id="theme-toggle" type="button">Toggle theme</button>'
        '<button onclick="window.print()" type="button">Print</button>'
        '</div></header>\n'
        '<main>\n'
        '<section class="summary">'
        f'<div class="card accuracy"><div class="label">Accuracy</div><div class="value">{accuracy_pct}%</div></div>'
        f'<div class="card"><div class="label">Passed</div><div class="value">{report.passed}</div></div>'
        f'<div class="card"><div class="label">Failed</div><div class="value">{report.failed}</div></div>'
        f'<div class="card"><div class="label">Total</div><div class="value">{report.total}</div></div>'
        '</section>\n'
        f'{failures_section}'
        '<h2>Cases</h2>\n'
        '<table><thead><tr><th>id</th><th>status</th><th>category</th><th>question</th><th>iter</th><th>time</th></tr></thead>'
        f'<tbody>{"".join(rows_html)}</tbody></table>\n'
        '</main>\n'
        f'<script>{_HTML_SCRIPT}</script>\n'
        '</body></html>\n'
    )
    p.write_text(html_doc, encoding="utf-8")
