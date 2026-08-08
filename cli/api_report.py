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


def _drift_sign(kind: str) -> str:
    if kind == "removed":
        return "−"  # minus
    if kind == "added":
        return "+"
    return "~"  # type-changed / became-nullable / element-type-changed


def _drift_type_text(d: dict) -> str:
    from_t = d.get("expected_type")
    to_t = d.get("actual_type")
    frm = "" if from_t is None else str(from_t)
    to = "" if to_t is None else str(to_t)
    kind = d.get("kind")
    if kind == "removed":
        return frm
    if kind == "added":
        return to
    return f"{frm or '?'} → {to or 'null'}"


def _render_schema_drift(drift) -> str:
    """Render the schema-drift changes block — Option A (plain-words, grouped),
    mirroring web/static/api/components/schema-diff-view.js. Returns '' when
    there is nothing to show."""
    if not isinstance(drift, dict):
        return ""
    diffs = drift.get("differences") or []
    if not diffs:
        return ""
    brk = drift.get("breaking_count") or 0
    add = drift.get("additive_count") or 0

    def _row(d: dict, color: str) -> str:
        return (
            '<div style="display:flex;align-items:baseline;gap:8px;padding:1px 0;'
            'font-family:monospace;font-size:12px">'
            f'<span style="color:{color};flex:none;width:10px;text-align:center;'
            f'font-weight:700">{_drift_sign(d.get("kind") or "")}</span>'
            f'<span style="flex:1;min-width:0;word-break:break-all">{_esc(d.get("path") or "")}</span>'
            f'<span style="color:#57606a;font-size:11px;flex:none;white-space:nowrap">'
            f'{_esc(_drift_type_text(d))}</span>'
            '</div>'
        )

    def _group(label: str, color: str, rows: list) -> str:
        if not rows:
            return ""
        return (
            f'<div style="font-size:10px;font-weight:700;text-transform:uppercase;'
            f'letter-spacing:.05em;color:{color};margin:8px 0 2px">{label}</div>'
            + "".join(rows)
        )

    breaking_rows = [_row(d, "#cf222e") for d in diffs if d.get("severity") == "breaking"]
    added_rows = [_row(d, "#9a6700") for d in diffs if d.get("severity") != "breaking"]
    parts = []
    if brk:
        parts.append(f"{brk} breaking")
    if add:
        parts.append(f"{add} added")
    return (
        '<div style="margin-bottom:14px">'
        '<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
        'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Schema Drift</div>'
        f'<div style="font-size:11px;color:#57606a;margin-bottom:2px">'
        f'Schema changed — {", ".join(parts)}</div>'
        + _group("Breaking", "#cf222e", breaking_rows)
        + _group("Added", "#9a6700", added_rows)
        + '</div>'
    )


_NEG_SEV = {
    "critical": ("#cf222e", "‼"),
    "major": ("#9a6700", "✗"),
    "minor": ("#57606a", "!"),
    "none": ("#1a7f37", "✓"),
}
_NEG_CAT_LABEL = {
    "input-validation": "Input validation",
    "request-level": "Request-level",
    "injection": "Injection / fuzz",
}
_NEG_CAT_ORDER = ["input-validation", "request-level", "injection"]
_NEG_CAT_COLOR = {"input-validation": "#0969da", "request-level": "#9a6700", "injection": "#cf222e"}
_NEG_CAT_CAPTION = {
    "input-validation": 'expects <b style="color:#0969da;font-family:monospace">4xx</b>',
    "request-level": "each row own code",
    "injection": 'checks <b style="color:#0969da;font-family:monospace">no 500 · not reflected</b>',
}
# kind → (text color, cell/tag background). Mirrors the JS qcn-c-* / qcn-*tag.* rules.
_NEG_KIND = {
    "g": ("#1a7f37", "rgba(26,127,55,.10)"),
    "r": ("#cf222e", "rgba(207,34,46,.12)"),
    "a": ("#9a6700", "rgba(154,103,0,.14)"),
    "m": ("#57606a", "rgba(87,96,106,.10)"),
}
_NEG_SUB = {
    "missing-required": "Missing", "wrong-type": "Wrong type", "null": "Null",
    "empty": "Empty", "boundary-min": "Below min", "boundary-max": "Above max",
    "boundary-minlength": "Too short", "boundary-maxlength": "Too long",
    "enum": "Bad enum", "format": "Bad format", "extra-field": "Extra field",
    "oversized": "Oversized", "no-auth": "No auth", "garbage-token": "Bad token",
    "wrong-method": "Wrong method", "wrong-content-type": "Bad Content-Type",
    "unknown-route": "Unknown route", "malformed-json": "Malformed JSON",
    "sqli": "SQLi", "xss": "XSS", "path-traversal": "Traversal", "null-byte": "Null byte",
}


def _neg_sub(s):
    return _NEG_SUB.get(s, s or "")


def _neg_field(t):
    t = t or ""
    if t.startswith("body."):
        return t[5:], "Body field"
    if t.startswith("param."):
        return t[6:], "Query param"
    return t, ""


def _neg_5xx(a):
    return isinstance(a, int) and a >= 500


def _neg_kind(c) -> str:
    if c.get("passed"):
        return "g"
    if c.get("false_pass"):
        return "r"
    if c.get("category") == "injection":
        return "r"
    if c.get("severity") == "major":
        return "a"
    if c.get("severity") == "minor":
        return "m"
    return "r"


def _neg_tag(c) -> str:
    if c.get("passed"):
        return "SAFE" if c.get("category") == "injection" else "REJECTED"
    if c.get("false_pass"):
        return "FALSE PASS"
    if c.get("category") == "injection":
        return "REFLECTED" if c.get("reflected") else ("SERVER ERROR" if _neg_5xx(c.get("actual_status")) else "FAILED")
    if c.get("severity") == "major":
        return "SERVER ERROR" if _neg_5xx(c.get("actual_status")) else "WRONG STATUS"
    if c.get("severity") == "minor":
        return "ERRORED" if c.get("actual_status") is None else "WRONG CODE"
    return "CRITICAL"


def _neg_rank(c) -> int:
    if c.get("false_pass"):
        return 0
    if not c.get("passed") and c.get("severity") == "critical":
        return 1
    if not c.get("passed") and c.get("severity") == "major":
        return 2
    if not c.get("passed") and c.get("severity") == "minor":
        return 3
    if not c.get("passed"):
        return 4
    return 5


def _neg_tag_html(c, width="104px") -> str:
    k = _neg_kind(c)
    color, bg = _NEG_KIND[k]
    return (
        f'<span style="flex:none;width:{width};text-align:center;font-size:9.5px;font-weight:700;'
        f'text-transform:uppercase;letter-spacing:.03em;padding:2px 0;border-radius:4px;'
        f'color:{color};background:{bg}">{_neg_tag(c)}</span>'
    )


def _neg_cat_head(cat, cl) -> str:
    rej = sum(1 for c in cl if c.get("passed"))
    return (
        '<div style="display:flex;align-items:center;gap:10px;margin:0 0 6px;padding-bottom:5px;'
        'border-bottom:1px solid #d0d7de">'
        f'<span style="width:8px;height:8px;border-radius:2px;flex:none;background:{_NEG_CAT_COLOR.get(cat, "#57606a")}"></span>'
        f'<span style="font-size:11.5px;font-weight:700;letter-spacing:.03em;text-transform:uppercase;color:#24292f">'
        f'{_esc(_NEG_CAT_LABEL.get(cat, cat))}</span>'
        f'<span style="font-size:11px;color:#57606a">{rej} of {len(cl)} rejected</span>'
        f'<span style="margin-left:auto;font-size:10.5px;color:#24292f;background:rgba(9,105,218,.08);'
        f'border:1px solid #d0d7de;border-radius:999px;padding:2px 10px;white-space:nowrap">'
        f'{_NEG_CAT_CAPTION.get(cat, "")}</span></div>'
    )


def _neg_cell(c) -> str:
    if not c:
        return ('<td style="text-align:center;padding:2px 3px">'
                '<span style="display:flex;align-items:center;justify-content:center;min-height:28px;'
                'color:#8c959f;opacity:.4">·</span></td>')
    k = _neg_kind(c)
    color, bg = _NEG_KIND[k]
    code = "—" if c.get("actual_status") is None else c.get("actual_status")
    refl = ('<small style="display:block;font-size:8px;font-weight:600;text-transform:uppercase;'
            'opacity:.85;margin-top:1px">refl</small>') if c.get("reflected") else ""
    return (
        f'<td style="text-align:center;padding:2px 3px">'
        f'<span style="display:flex;flex-direction:column;align-items:center;justify-content:center;'
        f'min-height:28px;padding:3px 5px;border-radius:6px;font-family:monospace;font-weight:700;'
        f'font-size:12px;line-height:1.15;color:{color};background:{bg};border:1px solid {bg}">'
        f'{_esc(str(code))}{refl}</span></td>'
    )


def _neg_grid_block(cat, cl) -> str:
    subs, tgts, grid = [], [], {}
    for c in cl:
        if c.get("subtype") not in subs:
            subs.append(c.get("subtype"))
        if c.get("target") not in grid:
            grid[c.get("target")] = {}
            tgts.append(c.get("target"))
        grid[c.get("target")][c.get("subtype")] = c
    head = '<th style="text-align:left;width:150px;padding:5px 6px 7px;color:#57606a;font-weight:600;font-size:9.5px;text-transform:uppercase;letter-spacing:.03em">Field</th>'
    for s in subs:
        head += f'<th style="text-align:center;padding:5px 6px 7px;color:#57606a;font-weight:600;font-size:9.5px;text-transform:uppercase;letter-spacing:.03em">{_esc(_neg_sub(s))}</th>'
    body = ""
    for t in tgts:
        n, kind_lbl = _neg_field(t)
        kk = f'<span style="display:block;font-size:8.5px;text-transform:uppercase;letter-spacing:.04em;color:#8c959f;margin-top:1px">{_esc(kind_lbl)}</span>' if kind_lbl else ""
        body += (
            '<tr><td style="padding:2px 3px">'
            f'<span style="font-family:monospace;color:#24292f;font-weight:600;font-size:12px">{_esc(n)}</span>{kk}</td>'
            + "".join(_neg_cell(grid[t].get(s)) for s in subs) + '</tr>'
        )
    return (
        '<div style="margin-top:16px">' + _neg_cat_head(cat, cl)
        + '<div style="overflow-x:auto"><table style="border-collapse:separate;border-spacing:0;width:100%;table-layout:fixed">'
        + f'<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
        + '</div>'
    )


def _neg_list_block(cat, cl) -> str:
    rows = ""
    for c in sorted(cl, key=_neg_rank):
        fail = not c.get("passed")
        msg = (c.get("note") or "") if fail else f'rejected correctly — got {"—" if c.get("actual_status") is None else c.get("actual_status")}'
        bg = "background:rgba(207,34,46,.10);" if fail else ""
        rows += (
            f'<div style="display:flex;align-items:center;gap:10px;padding:5px 8px;'
            f'border-bottom:1px solid #eaeef2;border-radius:5px;{bg}">'
            f'<span style="font-weight:600;font-size:12px;color:#24292f;min-width:150px">{_esc(_neg_sub(c.get("subtype")) or _neg_field(c.get("target"))[0])}</span>'
            + _neg_tag_html(c)
            + f'<span style="flex:1;min-width:0;font-size:11.5px;color:#57606a">{_esc(msg)}</span></div>'
        )
    return '<div style="margin-top:16px">' + _neg_cat_head(cat, cl) + f'<div>{rows}</div></div>'


def _render_negative(nr) -> str:
    """Render the negative-testing result block for the report, mirroring
    web/static/api/components/negative-view.js (headline + count chips + a
    per-category outcome heatmap + a findings list). Returns '' when empty."""
    if not isinstance(nr, dict):
        return ""
    cases = nr.get("cases") or []
    counts = nr.get("counts") or {}
    if not cases or not counts.get("total"):
        return ""

    total = len(cases)
    rej = fp = srv = other = crit_inj = 0
    for c in cases:
        if c.get("passed"):
            rej += 1
        elif c.get("false_pass"):
            fp += 1
        else:
            if _neg_5xx(c.get("actual_status")):
                srv += 1
            else:
                other += 1
            if c.get("category") == "injection" and (c.get("reflected") or _neg_5xx(c.get("actual_status"))):
                crit_inj += 1

    worst = nr.get("worst_severity") or "none"
    if worst == "critical":
        hcolor, hbg, hicn = "#cf222e", "rgba(207,34,46,.08)", "⛔"
    elif worst == "none":
        hcolor, hbg, hicn = "#1a7f37", "rgba(26,127,55,.08)", "✓"
    else:
        hcolor, hbg, hicn = "#9a6700", "rgba(154,103,0,.10)", "⚠"

    if fp:
        htxt = f'{fp} false pass{"es" if fp > 1 else ""} — API accepted invalid input'
    elif crit_inj:
        htxt = f'{crit_inj} critical issue{"s" if crit_inj > 1 else ""} on fuzzed input'
    elif total - rej > 0:
        htxt = f'{total - rej} returned the wrong status'
    else:
        htxt = f'All {total} invalid inputs correctly rejected'

    head = (
        f'<div style="display:flex;align-items:center;gap:10px;padding:10px 13px;border-radius:8px;'
        f'margin-bottom:10px;border:1px solid {hcolor};background:{hbg}">'
        f'<span style="font-size:15px;flex:none;color:{hcolor}">{hicn}</span>'
        f'<span style="font-size:13px;font-weight:700;color:{hcolor}">{_esc(htxt)}</span>'
        f'<span style="margin-left:auto;font-size:11px;color:#57606a;font-weight:500;white-space:nowrap">{rej} / {total} rejected</span></div>'
    )

    def _chip(color, label, n):
        border = ";border-color:#cf222e" if color == "#cf222e" else ""
        return (f'<span style="font-size:10.5px;font-weight:600;padding:3px 9px;border-radius:999px;'
                f'border:1px solid #d0d7de{border};color:{color}">{label} <b>{n}</b></span>')

    chips = '<div style="display:flex;gap:7px;flex-wrap:wrap;margin:0 0 10px">' + _chip("#1a7f37", "REJECTED", rej)
    if fp:
        chips += _chip("#cf222e", "FALSE PASS", fp)
    if srv:
        chips += _chip("#9a6700", "SERVER ERROR", srv)
    if other:
        chips += _chip("#57606a", "FAILED", other)
    chips += "</div>"

    legend = (
        '<div style="display:flex;gap:13px;flex-wrap:wrap;font-size:10px;color:#57606a;margin:0 0 12px">'
        '<span><i style="width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:4px;background:#1a7f37"></i>rejected</span>'
        '<span><i style="width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:4px;background:#cf222e"></i>false pass / reflected</span>'
        '<span><i style="width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:4px;background:#9a6700"></i>server error</span>'
        '<span><i style="width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:4px;background:#57606a"></i>wrong code</span>'
        '<span>· = not applicable</span></div>'
    )

    by_cat: dict = {}
    for c in cases:
        by_cat.setdefault(c.get("category", "other"), []).append(c)
    groups = ""
    for cat in _NEG_CAT_ORDER:
        if cat in by_cat:
            groups += _neg_list_block(cat, by_cat[cat]) if cat == "request-level" else _neg_grid_block(cat, by_cat[cat])
    for cat, cl in by_cat.items():
        if cat not in _NEG_CAT_ORDER:
            groups += _neg_grid_block(cat, cl)

    return (
        '<div style="margin-bottom:14px">'
        '<div style="font-size:11px;font-weight:700;text-transform:uppercase;'
        'letter-spacing:.05em;color:#57606a;margin-bottom:6px">Negative Testing</div>'
        + head + chips + legend + groups + '</div>'
    )


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
        drift = rr.get("schema_drift")
        drift_diffs = drift.get("differences") if isinstance(drift, dict) else None
        drift_breaking = (drift.get("breaking_count") or 0) if isinstance(drift, dict) else 0
        drift_pill = ""
        if drift_diffs:
            _dc = "#cf222e" if drift_breaking else "#9a6700"
            _dbg = "rgba(207,34,46,.10)" if drift_breaking else "rgba(154,103,0,.10)"
            drift_pill = (
                f'<span style="margin-left:8px;background:{_dbg};color:{_dc};font-size:10px;'
                f'font-weight:600;padding:1px 6px;border-radius:4px" title="Response schema drift">'
                f'schema Δ {len(drift_diffs)}</span>'
            )

        neg = rr.get("negative_result")
        neg_counts = neg.get("counts") if isinstance(neg, dict) else None
        neg_pill = ""
        if neg_counts and neg_counts.get("total"):
            _nw = neg.get("worst_severity") or "none"
            _nc, _ng = _NEG_SEV.get(_nw, _NEG_SEV["none"])
            _nbg = {"critical": "rgba(207,34,46,.10)", "major": "rgba(154,103,0,.10)",
                    "minor": "rgba(87,96,106,.12)", "none": "rgba(26,127,55,.10)"}.get(_nw, "rgba(26,127,55,.10)")
            neg_pill = (
                f'<span style="margin-left:8px;background:{_nbg};color:{_nc};font-size:10px;'
                f'font-weight:600;padding:1px 6px;border-radius:4px" title="Negative testing">'
                f'{_ng} neg {neg_counts.get("passed", 0)}/{neg_counts.get("total", 0)}</span>'
            )

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
            f'{_render_schema_drift(drift)}'
            f'{_render_negative(neg)}'
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
            f'<td style="padding:10px 12px;font-size:13px;font-weight:500">{name}{drift_pill}{neg_pill}</td>'
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
        "error_message, started_at, finished_at, schema_drift, negative_result "
        "FROM api_request_results WHERE collection_run_id = ? ORDER BY order_index",
        (run_id,),
    ).fetchall()

    request_results = []
    for r in result_rows:
        rr = dict(r)
        for key in ("response_headers", "assertion_results", "schema_drift", "negative_result"):
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

    drift_count = sum(
        1 for rr in request_results
        if isinstance(rr.get("schema_drift"), dict)
        and (rr["schema_drift"].get("breaking_count") or 0) > 0
    )

    neg_fail_count = sum(
        1 for rr in request_results
        if isinstance(rr.get("negative_result"), dict)
        and (rr["negative_result"].get("worst_severity") in ("critical", "major"))
    )

    stats = (
        _stat_card(total, "Total")
        + _stat_card(passed, "Passed", "#1a7f37")
        + _stat_card(failed, "Failed", "#cf222e")
        + (_stat_card(error_count, "Errors", "#9a6700") if error_count else "")
        + (_stat_card(drift_count, "Schema Drift", "#cf222e") if drift_count else "")
        + (_stat_card(neg_fail_count, "Negative", "#cf222e") if neg_fail_count else "")
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
