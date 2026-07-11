"""Self-contained HTML report generator for API collection runs.

Mirrors cli/report.py — produces a single HTML file with no external deps.
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timezone

from cli.db import get_conn

try:
    from cli._version import __version__ as _AGENT_VERSION
except Exception:
    _AGENT_VERSION = ""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return str(value)


def _duration(started, finished) -> str:
    if not started or not finished:
        return "—"
    try:
        d = (
            datetime.fromisoformat(finished) - datetime.fromisoformat(started)
        ).total_seconds()
        if d < 1:
            return f"{int(d * 1000)}ms"
        return f"{d:.1f}s"
    except (ValueError, TypeError):
        return "—"


def _render_body(body: str | None) -> str:
    if not body:
        return "<pre><em>(empty)</em></pre>"
    try:
        parsed = json.loads(body)
        formatted = json.dumps(parsed, indent=2, ensure_ascii=False)
        return f"<pre>{_esc(formatted)}</pre>"
    except (ValueError, TypeError):
        return f"<pre>{_esc(body[:8000])}</pre>"


_OP_LABELS = {
    "eq": "equals", "ne": "does not equal", "lt": "is less than",
    "gt": "is greater than", "contains": "contains",
    "exists": "exists", "not_exists": "does not exist", "matches": "matches pattern",
}

_METHOD_COLORS = {
    "GET": "#0969da", "POST": "#1a7f37", "PUT": "#e16f24",
    "PATCH": "#9a6700", "DELETE": "#cf222e", "HEAD": "#6e40c9", "OPTIONS": "#57606a",
}


def _assertion_label(a: dict) -> str:
    atype = a.get("type", "")
    op = _OP_LABELS.get(a.get("op", "eq"), a.get("op", ""))
    val = _esc(str(a.get("value", "")))
    if atype == "status":
        return f"Status code {op} <strong>{val}</strong>"
    if atype == "json_path":
        path = _esc(a.get("path", "$"))
        return f"JSON path <code>{path}</code> {op} <strong>{val}</strong>"
    if atype == "header":
        key = _esc(a.get("key", ""))
        return f"Header <code>{key}</code> {op} <strong>{val}</strong>"
    if atype == "response_time":
        return f"Response time {op} <strong>{val}ms</strong>"
    if atype == "body_text":
        return f"Response body {op} <strong>{val}</strong>"
    return f"{_esc(atype)} {op} <strong>{val}</strong>"


def _render_assertions(assertions: list) -> str:
    if not assertions:
        return '<p style="color:#57606a;font-size:12px;margin:4px 0">No assertions defined</p>'
    rows = []
    for a in assertions:
        passed = a.get("passed", False)
        icon = "✓" if passed else "✗"
        color = "#1a7f37" if passed else "#cf222e"
        actual = _esc(str(a.get("actual"))) if a.get("actual") is not None else "—"
        expected = _esc(str(a.get("value"))) if a.get("value") is not None else "—"
        detail = (
            f'<span style="color:#57606a;font-family:monospace;font-size:11px">'
            f'expected: {expected} · got: {actual}</span>'
            if not passed else
            f'<span style="color:#57606a;font-family:monospace;font-size:11px">'
            f'got: {actual}</span>'
        )
        rows.append(
            f'<div style="display:flex;align-items:flex-start;gap:8px;'
            f'padding:5px 0;border-bottom:1px solid #f0f0f0">'
            f'<span style="color:{color};font-size:14px;width:18px;flex-shrink:0">{icon}</span>'
            f'<div><div style="font-size:12px">{_assertion_label(a)}</div>'
            f'<div>{detail}</div></div>'
            f'</div>'
        )
    return "".join(rows)


def _render_headers_table(headers) -> str:
    if not headers or not isinstance(headers, dict):
        return '<p style="color:#57606a;font-size:12px;margin:4px 0">No headers</p>'
    rows = "".join(
        f'<tr><td style="padding:3px 8px;font-weight:600;color:#57606a;width:220px;'
        f'font-size:12px;border-bottom:1px solid #eee">{_esc(k)}</td>'
        f'<td style="padding:3px 8px;font-size:12px;border-bottom:1px solid #eee;'
        f'font-family:monospace;word-break:break-all">{_esc(str(v))}</td></tr>'
        for k, v in headers.items()
    )
    return f'<table style="width:100%;border-collapse:collapse"><tbody>{rows}</tbody></table>'


def _render_request_rows(request_results: list) -> str:
    rows = []
    for i, rr in enumerate(request_results):
        rid = _esc(rr.get("id", str(i)))
        method = (rr.get("method") or "GET").upper()
        method_color = _METHOD_COLORS.get(method, "#57606a")
        name = _esc(rr.get("request_name") or "")
        url = _esc(rr.get("url") or "")
        status = rr.get("status") or "ERROR"
        code = rr.get("status_code")
        duration_ms = rr.get("duration_ms")
        assertions = rr.get("assertion_results") or []
        error_msg = rr.get("error_message")

        passed_count = sum(1 for a in assertions if a.get("passed"))
        total_count = len(assertions)
        status_color = {"PASSED": "#1a7f37", "FAILED": "#cf222e", "ERROR": "#9a6700"}.get(
            status, "#9a6700"
        )

        error_html = (
            f'<div style="background:#fff8f0;border:1px solid #f5c2a0;border-radius:6px;'
            f'padding:10px 14px;font-size:12px;color:#8a3a00;margin-bottom:10px">'
            f'<strong>Error:</strong> {_esc(error_msg)}</div>'
            if error_msg else ""
        )

        reason_html = ""
        if status != "PASSED":
            raw_body = rr.get("response_body") or ""
            if raw_body:
                try:
                    parsed_body = json.loads(raw_body)
                    if isinstance(parsed_body, dict):
                        pick = (parsed_body.get("error") or parsed_body.get("message")
                                or parsed_body.get("detail") or parsed_body.get("msg")
                                or parsed_body.get("reason") or parsed_body.get("errorMessage")
                                or parsed_body.get("description"))
                        if pick is None and isinstance(parsed_body.get("errors"), list) and parsed_body["errors"]:
                            e0 = parsed_body["errors"][0]
                            pick = e0 if isinstance(e0, str) else json.dumps(e0)
                        if pick is not None:
                            reason_html = (
                                f'<div style="color:#cf222e;margin-bottom:8px;padding:6px 8px;'
                                f'background:rgba(207,34,46,.07);border-left:3px solid #cf222e;'
                                f'border-radius:2px;font-size:11px;word-break:break-word">'
                                f'{_esc(str(pick))}</div>'
                            )
                except (ValueError, TypeError):
                    pass

        detail_html = (
            f'<tr class="det-{rid}" style="display:none">'
            f'<td colspan="8" style="padding:0;background:#f6f8fa;border-bottom:2px solid #d0d7de">'
            f'<div style="padding:14px 16px">'
            f'{error_html}'
            f'{reason_html}'
            f'<div style="margin-bottom:14px">'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Assertions</div>'
            f'{_render_assertions(assertions)}'
            f'</div>'
            f'<div style="margin-bottom:14px">'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Response Headers</div>'
            f'{_render_headers_table(rr.get("response_headers"))}'
            f'</div>'
            f'<div>'
            f'<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Response Body</div>'
            f'{_render_body(rr.get("response_body"))}'
            f'</div>'
            f'</div></td></tr>'
        )

        row_html = (
            f'<tr onclick="tog(\'{rid}\')" style="cursor:pointer;border-bottom:1px solid #eee" '
            f'onmouseover="this.style.background=\'#f6f8fa\'" '
            f'onmouseout="this.style.background=\'\'">'
            f'<td style="padding:10px 12px;font-size:12px;color:#57606a">{i + 1}</td>'
            f'<td style="padding:10px 12px">'
            f'<span style="display:inline-block;background:{method_color};color:#fff;'
            f'font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;'
            f'min-width:50px;text-align:center">{_esc(method)}</span></td>'
            f'<td style="padding:10px 12px;font-size:13px;font-weight:500">{name}</td>'
            f'<td style="padding:10px 12px;font-size:11px;font-family:monospace;'
            f'color:#57606a;max-width:260px;overflow:hidden;text-overflow:ellipsis;'
            f'white-space:nowrap" title="{url}">{url}</td>'
            f'<td style="padding:10px 12px">'
            f'<span style="background:{status_color};color:#fff;font-size:11px;'
            f'font-weight:700;padding:2px 8px;border-radius:6px">{_esc(status)}</span></td>'
            f'<td style="padding:10px 12px;font-size:13px">'
            f'{_esc(str(code)) if code is not None else "—"}</td>'
            f'<td style="padding:10px 12px;font-size:13px">'
            f'{_esc(str(duration_ms)) + "ms" if duration_ms is not None else "—"}</td>'
            f'<td style="padding:10px 12px;font-size:12px;color:#57606a">'
            f'{passed_count}/{total_count} passed</td>'
            f'</tr>'
        )

        rows.append(row_html + detail_html)

    return "".join(rows)


_HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>QAClan API Report — {title}</title>
<style>
*{{box-sizing:border-box}}
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f5f7;color:#1c2128}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 16px}}
h1{{font-size:22px;font-weight:700;margin:0 0 4px}}
pre{{background:#fff;border:1px solid #d0d7de;border-radius:6px;padding:8px 10px;
  font-size:11px;font-family:ui-monospace,Menlo,monospace;overflow-x:auto;
  white-space:pre-wrap;word-break:break-word;margin:0;max-height:320px;overflow-y:auto}}
footer{{color:#8c959f;font-size:11px;margin-top:24px;text-align:center}}
</style>
<script>
function tog(id){{
  var r=document.querySelector('.det-'+id);
  if(r)r.style.display=r.style.display==='table-row'?'none':'table-row';
}}
</script>
</head>
<body>
<div class="wrap">
  <div style="display:flex;align-items:center;gap:12px;margin-bottom:4px;flex-wrap:wrap">
    <h1>{title}</h1>
    <span style="background:{status_bg};color:#fff;font-size:13px;font-weight:700;
      padding:4px 14px;border-radius:20px">{status}</span>
  </div>
  <div style="color:#57606a;font-size:13px;margin-bottom:16px">{meta}</div>
  <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:12px">{stats}</div>
  <div style="height:8px;border-radius:4px;background:#eee;overflow:hidden;margin-bottom:20px">
    <div style="height:100%;width:{passrate}%;background:#1a7f37"></div>
  </div>
  <div style="background:#fff;border:1px solid #d0d7de;border-radius:8px;overflow:hidden">
    <table style="width:100%;border-collapse:collapse">
      <thead>
        <tr style="background:#f6f8fa;border-bottom:1px solid #d0d7de">
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">#</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Method</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Name</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">URL</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Status</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Code</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Duration</th>
          <th style="padding:8px 12px;font-size:11px;font-weight:600;text-transform:uppercase;
            letter-spacing:.04em;color:#57606a;text-align:left">Assertions</th>
        </tr>
      </thead>
      <tbody>
        {rows}
      </tbody>
    </table>
  </div>
  <footer>QAClan Agent {version} &middot; generated {generated}</footer>
</div>
</body>
</html>
"""


def _stat_card(n, label, color="#1c2128") -> str:
    return (
        f'<div style="background:#fff;border:1px solid #d0d7de;border-radius:8px;'
        f'padding:10px 18px;text-align:center;min-width:90px">'
        f'<div style="font-size:24px;font-weight:700;color:{color}">{_esc(str(n))}</div>'
        f'<div style="font-size:11px;text-transform:uppercase;letter-spacing:.04em;'
        f'color:#57606a">{label}</div>'
        f'</div>'
    )


def generate_api_html_report(run_id: str, project_id: str) -> str:
    """Build self-contained HTML report for one API collection run.
    Raises ValueError if run not found."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, collection_name, env_name, status, total, passed, failed, "
        "error_count, started_at, finished_at "
        "FROM api_collection_runs WHERE id = ? AND project_id = ?",
        (run_id, project_id),
    ).fetchone()
    if not row:
        raise ValueError(f"API collection run {run_id} not found")
    run = dict(row)

    result_rows = conn.execute(
        "SELECT id, request_name, method, url, status, status_code, "
        "response_body, response_headers, duration_ms, assertion_results, "
        "error_message, started_at, finished_at "
        "FROM api_request_results WHERE collection_run_id = ? ORDER BY order_index",
        (run_id,),
    ).fetchall()

    request_results = []
    for r in result_rows:
        rr = dict(r)
        for key in ("response_headers", "assertion_results"):
            if isinstance(rr.get(key), str):
                try:
                    rr[key] = json.loads(rr[key])
                except (ValueError, TypeError):
                    rr[key] = None
        request_results.append(rr)

    total = run.get("total") or 0
    passed = run.get("passed") or 0
    failed = run.get("failed") or 0
    error_count = run.get("error_count") or 0
    passrate = int((passed / total) * 100) if total else 0

    status = run.get("status", "ERROR")
    status_bg = "#1a7f37" if status == "PASSED" else "#cf222e"

    title = _esc(run.get("collection_name") or "API Run")
    env = _esc(run.get("env_name") or "No environment")
    duration = _duration(run.get("started_at"), run.get("finished_at"))
    meta = (
        f"Environment: {env} · "
        f"Started: {_fmt_dt(run.get('started_at'))} · "
        f"Duration: {duration}"
    )

    stats = (
        _stat_card(total, "Total")
        + _stat_card(passed, "Passed", "#1a7f37")
        + _stat_card(failed, "Failed", "#cf222e")
        + (_stat_card(error_count, "Errors", "#9a6700") if error_count else "")
        + _stat_card(f"{passrate}%", "Pass Rate")
        + _stat_card(duration, "Duration")
    )

    rows_html = _render_request_rows(request_results)
    if not rows_html:
        rows_html = (
            '<tr><td colspan="8" style="text-align:center;padding:24px;color:#57606a">'
            "No requests were run.</td></tr>"
        )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return _HTML.format(
        title=title,
        status=_esc(status),
        status_bg=status_bg,
        meta=meta,
        stats=stats,
        passrate=passrate,
        rows=rows_html,
        version=_esc(_AGENT_VERSION),
        generated=generated,
    )
