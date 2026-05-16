"""Offline run report generator.

Produces a single self-contained HTML file — screenshots inlined as base64
data URIs — that opens in any browser with no server and no internet. Used by
both the CLI (`qaclan runs report`) and the web UI download button.

See docs/error-reporting-plan.md (section 4).
"""

from __future__ import annotations

import base64
import html
import json
import mimetypes
from datetime import datetime
from typing import Optional

from cli.db import get_conn

try:
    from cli._version import __version__ as _AGENT_VERSION
except Exception:  # pragma: no cover - version is best-effort
    _AGENT_VERSION = ""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _inline_screenshot(path: Optional[str]) -> Optional[str]:
    """Read a screenshot file and return a base64 data URI, or None."""
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            raw = f.read()
        mime = mimetypes.guess_type(path)[0] or "image/png"
        return f"data:{mime};base64," + base64.b64encode(raw).decode("ascii")
    except Exception:
        return None


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
        d = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
        return f"{d:.1f}s"
    except (ValueError, TypeError):
        return "—"


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QAClan Run Report — {title}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0;
    background: #f4f5f7; color: #1c2128; }}
  .wrap {{ max-width: 900px; margin: 0 auto; padding: 24px; }}
  h1 {{ font-size: 20px; margin: 0 0 4px; }}
  .meta {{ color: #57606a; font-size: 13px; margin-bottom: 16px; }}
  .stats {{ display: flex; gap: 12px; margin: 16px 0; flex-wrap: wrap; }}
  .stat {{ background: #fff; border: 1px solid #d0d7de; border-radius: 8px;
    padding: 10px 16px; min-width: 80px; text-align: center; }}
  .stat .n {{ font-size: 22px; font-weight: 700; }}
  .stat .l {{ font-size: 11px; text-transform: uppercase; color: #57606a; }}
  .pass {{ color: #1a7f37; }} .fail {{ color: #cf222e; }} .skip {{ color: #9a6700; }}
  .bar {{ height: 10px; border-radius: 5px; background: #cf222e; overflow: hidden; margin: 8px 0 16px; }}
  .bar > div {{ height: 100%; background: #1a7f37; }}
  .chips {{ display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 16px; }}
  .chip {{ background: #fff; border: 1px solid #d0d7de; border-radius: 6px;
    padding: 2px 8px; font-size: 12px; font-weight: 600; color: #cf222e; }}
  .card {{ background: #fff; border: 1px solid #d0d7de; border-radius: 8px;
    padding: 14px 16px; margin-bottom: 12px; border-left: 3px solid #d0d7de; }}
  .card.s-pass {{ border-left-color: #1a7f37; }}
  .card.s-fail {{ border-left-color: #cf222e; }}
  .card.s-skip {{ border-left-color: #9a6700; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: baseline; }}
  .card-name {{ font-weight: 600; font-size: 14px; }}
  .badge {{ font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; color: #fff; }}
  .badge.b-pass {{ background: #1a7f37; }}
  .badge.b-fail {{ background: #cf222e; }}
  .badge.b-skip {{ background: #9a6700; }}
  .ecat {{ display: inline-block; font-size: 10px; font-weight: 700; color: #fff;
    background: #cf222e; border-radius: 5px; padding: 2px 7px; margin-right: 6px; }}
  .ecat.warning {{ background: #9a6700; }}
  /* Boxed error card — mirrors the web UI Execution History card. The
     outer .card already carries the red status bar, so .ecard has none. */
  .ecard {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 8px;
    padding: 12px 14px; margin-top: 8px; }}
  .ecard-head {{ margin-bottom: 4px; }}
  .ecard-title {{ font-size: 13px; font-weight: 600; color: #1f2328; }}
  .ecard-msg {{ font-size: 13px; color: #1f2328; margin-top: 2px; line-height: 1.5; }}
  .ecard-next {{ font-size: 12px; color: #424a53; line-height: 1.45;
    background: #ddf4ff; border-radius: 6px; padding: 6px 9px; margin-top: 7px; }}
  .ecard-next-label {{ display: block; font-size: 9.5px; font-weight: 700;
    letter-spacing: 0.04em; text-transform: uppercase; color: #0969da;
    margin-bottom: 2px; }}
  .ecard-diag {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;
    padding-top: 8px; border-top: 1px solid #d0d7de; }}
  .dpill {{ display: inline-flex; align-items: center; gap: 5px; background: #fff;
    border: 1px solid #d0d7de; border-radius: 10px; padding: 2px 8px; }}
  .dpill-k {{ font-size: 9.5px; font-weight: 700; letter-spacing: 0.04em;
    text-transform: uppercase; color: #57606a; }}
  .dpill-v {{ font-size: 11.5px; color: #424a53; }}
  .dpill-v code {{ font-size: 11px; color: #1f2328; }}
  code {{ font-family: ui-monospace, Menlo, monospace; font-size: 12px; }}
  img.shot {{ max-width: 100%; border: 1px solid #d0d7de; border-radius: 6px; margin: 8px 0; }}
  details {{ margin-top: 8px; }}
  summary {{ cursor: pointer; font-size: 12px; color: #57606a; }}
  pre {{ background: #f6f8fa; border: 1px solid #d0d7de; border-radius: 6px;
    padding: 8px; font-size: 11px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }}
  .diag {{ font-size: 12px; margin-top: 6px; }}
  .diag b {{ display: block; margin-top: 6px; color: #57606a; }}
  footer {{ color: #8c959f; font-size: 11px; margin-top: 24px; text-align: center; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{title}</h1>
  <div class="meta">{meta}</div>
  <div class="stats">{stats}</div>
  <div class="bar"><div style="width:{passrate}%"></div></div>
  {chips}
  {scripts}
  <footer>QAClan Agent {version} · run {run_id} · generated {generated}</footer>
</div>
</body>
</html>
"""


def generate_html_report(run_id: str) -> str:
    """Build a self-contained HTML report for a run. Raises ValueError if the
    run does not exist."""
    conn = get_conn()
    run = conn.execute(
        "SELECT sr.*, s.name AS suite_name, e.name AS env_name "
        "FROM suite_runs sr JOIN suites s ON sr.suite_id = s.id "
        "LEFT JOIN environments e ON sr.environment_id = e.id "
        "WHERE sr.id = ?",
        (run_id,),
    ).fetchone()
    if not run:
        raise ValueError(f"Run {run_id} not found")

    scripts = conn.execute(
        "SELECT scr.*, s.name AS script_name "
        "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
        "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
        (run_id,),
    ).fetchall()

    total = run["total"] or 0
    passed = run["passed"] or 0
    failed = run["failed"] or 0
    skipped = run["skipped"] or 0
    passrate = int((passed / total) * 100) if total else 0

    title = f"{run['suite_name']} — {run['status']}"
    meta = (
        f"Environment: {_esc(run['env_name'] or 'none')} · "
        f"Browser: {_esc(run['browser'] or 'chromium')} · "
        f"Resolution: {_esc(run['resolution'] or 'default')} · "
        f"Started: {_fmt_dt(run['started_at'])} · "
        f"Duration: {_duration(run['started_at'], run['finished_at'])}"
    )

    stats = "".join(
        f'<div class="stat"><div class="n {cls}">{n}</div><div class="l">{label}</div></div>'
        for n, label, cls in [
            (total, "Total", ""),
            (passed, "Passed", "pass"),
            (failed, "Failed", "fail"),
            (skipped, "Skipped", "skip"),
        ]
    )

    # Failures grouped by category.
    cat_counts: dict = {}
    parsed = []
    for scr in scripts:
        ed = None
        if scr["error_detail"]:
            try:
                ed = json.loads(scr["error_detail"])
            except (TypeError, ValueError):
                ed = None
        if scr["status"] == "FAILED" and ed and ed.get("category"):
            cat_counts[ed["category"]] = cat_counts.get(ed["category"], 0) + 1
        parsed.append((scr, ed))

    chips = ""
    if cat_counts:
        chips = '<div class="chips">' + "".join(
            f'<span class="chip">{_esc(c)} {n}</span>'
            for c, n in sorted(cat_counts.items(), key=lambda kv: -kv[1])
        ) + "</div>"

    scripts_html = "".join(_render_script(scr, ed) for scr, ed in parsed)

    version = ("v" + str(_AGENT_VERSION)) if _AGENT_VERSION else ""

    return _HTML_TEMPLATE.format(
        title=_esc(title),
        meta=meta,
        stats=stats,
        passrate=passrate,
        chips=chips,
        scripts=scripts_html,
        version=_esc(version),
        run_id=_esc(run_id),
        generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def _render_script(scr, ed) -> str:
    status = scr["status"] or "UNKNOWN"
    cls = {"PASSED": "s-pass", "FAILED": "s-fail", "SKIPPED": "s-skip"}.get(status, "")
    bcls = {"PASSED": "b-pass", "FAILED": "b-fail", "SKIPPED": "b-skip"}.get(status, "b-fail")
    dur = f"{scr['duration_ms']/1000:.1f}s" if scr["duration_ms"] else "—"

    parts = [
        f'<div class="card {cls}">',
        '<div class="card-head">',
        f'<span class="card-name">{_esc(scr["script_name"])}</span>',
        f'<span class="badge {bcls}">{_esc(status)}</span>',
        '</div>',
        f'<div class="enext">Duration: {dur}</div>',
    ]

    if status == "FAILED":
        if ed:
            sev = "warning" if ed.get("severity") == "warning" else ""
            inner = [
                '<div class="ecard">',
                f'<div class="ecard-head"><span class="ecat {sev}">'
                f'{_esc(ed.get("category"))}</span>'
                f'<span class="ecard-title">{_esc(ed.get("title"))}</span></div>',
                f'<div class="ecard-msg">{_esc(ed.get("message"))}</div>',
                f'<div class="ecard-next"><span class="ecard-next-label">'
                f'What to do</span>{_esc(ed.get("next_step"))}</div>',
            ]
            diag = _error_diag_html(ed)
            if diag:
                inner.append(diag)
            inner.append('</div>')
            parts.append("".join(inner))

        shot = _inline_screenshot(scr["screenshot_path"])
        if shot:
            parts.append(f'<img class="shot" src="{shot}" alt="Failure screenshot">')

        parts.append(_render_diagnostics(scr))

        if scr["error_message"]:
            parts.append(
                "<details><summary>Technical details</summary>"
                f"<pre>{_esc(scr['error_message'])}</pre></details>"
            )

    parts.append("</div>")
    return "".join(parts)


def _error_diag_html(ed) -> str:
    """The classifier's extracted fields as scannable pills — action, element,
    timeout, state, etc. Absent fields don't render. See error-reporting-plan §6.5."""
    items = []
    if ed.get("action"):
        items.append(("action", f'<code>{_esc(ed["action"])}</code>'))
    if ed.get("selector"):
        items.append(("element", f'<code>{_esc(ed["selector"])}</code>'))
    if ed.get("timeout_ms"):
        items.append(("timeout", f'{int(ed["timeout_ms"] / 1000)}s'))
    if ed.get("element_state"):
        items.append(("state", _esc(ed["element_state"])))
    if ed.get("match_count"):
        items.append(("matched", f'{ed["match_count"]} elements'))
    if ed.get("url"):
        items.append(("url", f'<code>{_esc(ed["url"])}</code>'))
    if ed.get("net_error"):
        items.append(("network", f'<code>{_esc(ed["net_error"])}</code>'))
    if not items:
        return ""
    pills = "".join(
        f'<span class="dpill"><span class="dpill-k">{k}</span>'
        f'<span class="dpill-v">{v}</span></span>'
        for k, v in items
    )
    return f'<div class="ecard-diag">{pills}</div>'


def _render_diagnostics(scr) -> str:
    def _load(col):
        if not scr[col]:
            return []
        try:
            return json.loads(scr[col]) or []
        except (TypeError, ValueError):
            return []

    console_logs = _load("console_log")
    network_logs = _load("network_log")
    if not console_logs and not network_logs:
        return ""

    rows = []
    if console_logs:
        rows.append("<b>Console errors/warnings</b>")
        rows += [f"{_esc(c.get('type'))}: {_esc(c.get('text'))}<br>" for c in console_logs]
    if network_logs:
        rows.append("<b>Network failures</b>")
        rows += [
            f"{_esc(n.get('method'))} {_esc(n.get('url'))}"
            f"{' — ' + _esc(n.get('failure')) if n.get('failure') else ''}<br>"
            for n in network_logs
        ]
    return f'<div class="diag">{"".join(rows)}</div>'
