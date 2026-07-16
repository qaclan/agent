# API Script-Run Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Revision 2026-07-17:** Spec changed capture from always-on to **opt-in, off by default** (see spec's Section 0 and revision note). This plan now includes a new Task 1.5 (DB column + route + UI checkbox wiring) before the harness tasks, and Tasks 3-6 gate their capture branch behind `QACLAN_CAPTURE_REQUESTS` plus truncate bodies at 200KB. Also fixes a gap in the original plan: `web/routes/scripts.py:run_script_solo` is a second call site that sets harness env vars independently of `execute_run` and was not covered by Task 7 — Task 1.5 now covers it too.

**Goal:** During a suite run, when the user opts in via a checkbox, passively record the XHR/fetch traffic the browser makes, redact sensitive values the same way the other three Discovery paths do, surface it as a "Captured Requests" section on the run-detail view with checkboxes, and let the user save selected entries through the existing shared Discovery save flow (Save as Flow / Save as Library, with folder suggestion) — with zero new backend save endpoints.

**Architecture:** Each of the 4 language harness templates (`python_strategy.py`, `javascript_strategy.py`, `javascript_test_strategy.py`, `typescript_test_strategy.py` — `typescript_strategy.py` inherits `javascript_strategy.py`'s template verbatim, so it needs no direct edit) gets a capture buffer bolted onto its existing `_track_network`/`_trackNetwork` handlers, gated behind a new `QACLAN_CAPTURE_REQUESTS` env var so opted-out runs do zero extra per-request work, capped at 200 entries with each body truncated at 200KB, filtered to the same resource types the other Discovery paths hide by default. On run completion the harness writes the raw capture into the same `*.artifacts.json` file it already writes `console_errors`/`network_failures` to (no new file — one new env var to gate it, per Task 1.5). `web/routes/runs.py` reads that file (as it already does), converts the raw capture through a new adapter — `cli/api_discovery/captured_request_parser.py` — that wraps each entry as a synthetic HAR entry and calls the **existing** `parse_har()`, so redaction (`_redact_sensitive`), the browser-header skip-list, query-param splitting, and body/schema inference are reused, not duplicated. The already-redacted, already-shaped array is stored in a new `script_runs.captured_requests` column exactly the way `console_log`/`network_log` are stored today, and rendered in `app.js`'s existing per-script run-detail card via a new collapsible section that mirrors the existing "Diagnostics" toggle. "Save Selected" opens the **existing** `showRequestReviewModal()` (`request-review-modal.js`) with zero changes to it — the redacted array already matches the HAR-import request shape that modal (and its already-shipped Flow/Library radio + folder-suggestion checkbox from the variant-library and nested-folders specs) already consumes.

**Tech Stack:** Flask (`web/routes/runs.py`, existing per-route pattern — this route predates the routes/services/repos 3-layer split used in `web/api/`), raw `sqlite3` via `cli/db.py`, Python/JS/TS Playwright harness templates, vanilla JS (`web/static/app.js`, no build step).

**Spec:** `docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md`

## Global Constraints

- No automated test framework exists in this repo. Backend Python is verified with `python3 -c` inline assertions; harness template changes are verified by actually rendering the template and running it through the real Playwright runtime at `~/.qaclan/runtime/` against a local fixture HTTP server (not just a syntax check — Playwright event-handler races are a real risk in the JS/TS harnesses, see Task 4); frontend DOM changes are verified by running `python qaclan.py serve --port 7823` and clicking through, per this repo's established convention (see `docs/superpowers/plans/2026-07-10-api-variant-library-plan.md`, `docs/superpowers/plans/2026-07-11-nested-folders-drag-drop.md`).
- Python targets 3.10+ typing style (`str | None`, `list[dict]`).
- New SQL changes are one new `_migrate_xxx(conn)` function in `cli/db.py`, appended to the end of the call chain inside `init_db()` — never reorder or remove existing `_migrate_*` calls. The chain currently ends with `_migrate_nested_folders(conn)` (`cli/db.py:153`).
- **Redact once, at write time — never persist raw secrets.** The conversion from raw harness capture to the redacted, review-modal-ready shape happens in `web/routes/runs.py` before the `INSERT INTO script_runs`. The `script_runs.captured_requests` column only ever holds the already-redacted array — this matches how HAR import and Record APIs mode never persist raw secrets either (`cli/api_discovery/har_parser.py`'s `_redact_sensitive` runs at parse time, before anything is saved).
- **No new Discovery save endpoint, no new save-modal code.** The adapter's output must match the exact dict shape `cli/api_discovery/har_parser.py:parse_har()` already returns (`method, url, headers[], params[], body, body_type, name, request_schema, response_schema, response_status, response_headers, response_body, duration_ms`, headers/params as `{key,value,enabled}` arrays) so `showRequestReviewModal()` (`web/static/api/views/request-review-modal.js:90`) and the `/discover/save-requests` / `/discover/group-requests` / `/discover/save-library` routes it already posts to need zero changes.
- Every new/modified harness capture step is wrapped so a capture failure never fails the run (spec decision: "A capture failure on one request is swallowed; never fails the run").
- Cap is exactly 200 captured entries per run; entries past the cap are silently dropped, no warning surfaced (spec: "Out of Scope — Surfacing a warning when the 200-entry cap is hit").
- Each entry's `request_body`/`response_body` is independently truncated at 200KB (`_CAPTURE_BODY_CAP_BYTES = 200_000`), silently, same convention as the count cap.
- Filter out `resourceType` in `document`, `stylesheet`, `image`, `font`, `script` at harness capture time — same convention the spec calls out as already used by the other three discovery paths.
- **Capture is opt-in, off by default.** Every harness reads `QACLAN_CAPTURE_REQUESTS` ("1"/"0", default "0") once at startup; when off, the capture branch returns immediately as its first statement, before any per-request work. Both env-var-setting call sites — `web/routes/runs.py:execute_run` and `web/routes/scripts.py:run_script_solo` — must set it (Task 1.5).
- `window.api()` never throws — it returns `{ok: false, error}` on failure. Always check `res.ok === false`.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `cli/db.py` | Modify | New `_migrate_captured_requests` migration — adds `captured_requests`/`captured_requests_count` to `script_runs` AND `capture_requests` to `suite_runs` |
| `web/routes/runs.py` | Modify | Task 1.5: read `capture_requests` from request body, persist on `suite_runs`, set `QACLAN_CAPTURE_REQUESTS` child env. Task 7: read raw capture from artifacts JSON, redact/shape via the new adapter, persist to DB, include in `get_run()` and `execute_run()` responses |
| `web/routes/scripts.py` | Modify | Task 1.5: `run_script_solo` hardcodes `QACLAN_CAPTURE_REQUESTS=0` — second call site the original plan missed |
| `cli/api_discovery/captured_request_parser.py` | Create | `parse_captured_requests()` — wraps raw harness capture as synthetic HAR entries, reuses `parse_har()` for redaction/shaping |
| `cli/script_strategies/python_strategy.py` | Modify | Capture buffer + resource-type filter + `QACLAN_CAPTURE_REQUESTS` gate + body truncation wired into `_track_network`; emitted in `_write_artifacts` |
| `cli/script_strategies/javascript_strategy.py` | Modify | Same, JS harness (manual lifecycle); also owns the shared `_QACLAN_JS_NAMES` collision list used by JS-test/TS-test |
| `cli/script_strategies/javascript_test_strategy.py` | Modify | Same, `@playwright/test` fixture harness |
| `cli/script_strategies/typescript_test_strategy.py` | Modify | Same, TS-typed `@playwright/test` fixture harness |
| `web/static/app.js` | Modify | Task 1.5: "Capture API Requests" checkbox on the suite-run modal, wired into `POST /runs`. Task 8: new collapsible "Captured Requests" section per script-result card in `showRunResults()`; selection state; "Save Selected" wired to the existing `showRequestReviewModal()` |
| `web/static/style.css` | Modify | Styling for the new captured-request rows, reusing existing `.diag-*`/`.method-badge`/`.btn-ghost.btn-sm` classes |

No changes needed to: `typescript_strategy.py` (inherits `javascript_strategy.py`'s template), `request-review-modal.js`, `variant-comparison-modal.js`, any `web/api/routes/discovery.py` route, `cli/api_discovery/folder_suggester.py`, `cli/db.py`'s `api_folders`/`api_request_examples` tables — the entire Save as Flow / Save as Library / folder-suggestion pipeline already exists and is reused unmodified.

---

## Task 1: DB migration — `captured_requests` columns on `script_runs`

**Files:**
- Modify: `cli/db.py:153` (append call), after `_migrate_nested_folders(conn)` at line 220-222 (append function)

**Interfaces:**
- Produces: `script_runs.captured_requests` (TEXT, nullable — JSON array, already-redacted, review-modal-shaped) and `script_runs.captured_requests_count` (INTEGER DEFAULT 0), consumed by Task 7 (`runs.py` INSERT/SELECT).
- Produces: `suite_runs.capture_requests` (INTEGER DEFAULT 0 — the opt-in flag chosen for the run, same pattern as the existing `suite_runs.headless` column), consumed by Task 1.5 (`runs.py`'s `execute_run` INSERT) and `get_run()`'s response.

- [ ] **Step 1: Write the failing verification script**

`cli/db.py`'s `init_db()` takes a connection directly, so the test runs it against a throwaway sqlite file and inspects the resulting schema:

```bash
mkdir -p /tmp/qaclan_plan_verify
cat > /tmp/qaclan_plan_verify/test_migration.py <<'EOF'
import sqlite3, sys, os, tempfile
sys.path.insert(0, os.path.abspath("."))
from cli.db import init_db

tmpdb = tempfile.mktemp(suffix=".db")
conn = sqlite3.connect(tmpdb)
conn.row_factory = sqlite3.Row
init_db(conn)

cols = {row["name"] for row in conn.execute("PRAGMA table_info(script_runs)")}
assert "captured_requests" in cols, f"captured_requests column missing: {cols}"
assert "captured_requests_count" in cols, f"captured_requests_count column missing: {cols}"

suite_cols = {row["name"] for row in conn.execute("PRAGMA table_info(suite_runs)")}
assert "capture_requests" in suite_cols, f"suite_runs.capture_requests column missing: {suite_cols}"

print("OK: script_runs has captured_requests + captured_requests_count, suite_runs has capture_requests")
EOF
python3 /tmp/qaclan_plan_verify/test_migration.py
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/qaclan_plan_verify/test_migration.py`
Expected: `AssertionError: captured_requests column missing: {...}` (whichever assert hits first)

- [ ] **Step 3: Implement the migration**

In `cli/db.py`, add the new migration call right after `_migrate_nested_folders(conn)` (currently the last line of the `_migrate()`/`init_db()` chain, line 153):

```python
    _migrate_api_request_examples(conn)
    _migrate_nested_folders(conn)
    _migrate_captured_requests(conn)
```

Then add the function definition right after `_migrate_nested_folders` (after its closing `conn.commit()` at line 222):

```python
def _migrate_captured_requests(conn):
    """Add captured_requests (JSON array, already redacted/shaped via
    cli.api_discovery.captured_request_parser.parse_captured_requests) and
    captured_requests_count to script_runs, and the opt-in capture_requests
    flag to suite_runs (same pattern as suite_runs.headless).
    See docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md."""
    for col, coltype in [
        ("captured_requests", "TEXT"),
        ("captured_requests_count", "INTEGER DEFAULT 0"),
    ]:
        try:
            conn.execute(f"ALTER TABLE script_runs ADD COLUMN {col} {coltype}")
        except Exception:
            pass  # Column already exists
    try:
        conn.execute("ALTER TABLE suite_runs ADD COLUMN capture_requests INTEGER DEFAULT 0")
    except Exception:
        pass  # Column already exists
    conn.commit()
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python3 /tmp/qaclan_plan_verify/test_migration.py`
Expected: `OK: script_runs has captured_requests + captured_requests_count, suite_runs has capture_requests`

- [ ] **Step 5: Verify the real local DB migrates cleanly too**

Run: `python3 -c "from cli.db import get_conn, init_db; init_db(get_conn()); print('migrated real db OK')"`
Expected: `migrated real db OK` (no exception)

- [ ] **Step 6: Commit**

```bash
git add cli/db.py
git commit -m "feat(db): add captured_requests columns to script_runs"
```

---

## Task 1.5: Opt-in wiring — checkbox → `POST /runs` → `suite_runs.capture_requests` → `QACLAN_CAPTURE_REQUESTS`

**Files:**
- Modify: `web/routes/runs.py` — `execute_run` (`capture_requests = data.get(...)` alongside the existing `headless = data.get("headless", False)` at line 239; child env at line 555 alongside `QACLAN_HEADLESS`; `suite_runs` INSERT at line 326-328; `get_run()`'s `sr.headless` select list at line 151)
- Modify: `web/routes/scripts.py` — `run_script_solo` (child env, alongside its own `QACLAN_HEADLESS` setting)
- Modify: `web/static/app.js` — suite-run modal (checkbox HTML near line 3990-3998, alongside `run-headless`/`run-stop-on-fail`; read + POST near line 4006/4017)

**Interfaces:**
- Consumes: `suite_runs.capture_requests` column (Task 1).
- Produces: `QACLAN_CAPTURE_REQUESTS` env var ("1"/"0") on the harness subprocess — consumed by Tasks 3-6 (all 4 harness templates gate their capture branch on this).
- Produces: `capture_requests` field on `get_run()`'s response (mirrors `headless`) so the run-detail view could show it was on/off (not required for this plan's UI, but keeps the row symmetric with the other run-config columns already selected there).

This must land before Tasks 3-6, since those tasks' harness capture branches check for this env var's presence.

- [ ] **Step 1: `runs.py` — read, persist, and pass through the flag**

At line 239, alongside `headless = data.get("headless", False)`:

```python
        capture_requests = bool(data.get("capture_requests", False))
```

Extend the `suite_runs` INSERT (lines 326-328) to add the column:

```python
            "INSERT INTO suite_runs (id, suite_id, project_id, environment_id, channel, status, total, started_at, browser, resolution, headless, capture_requests) "
            "VALUES (?, ?, ?, ?, ?, 'RUNNING', ?, ?, ?, ?, ?, ?)",
            (run_id, suite_id, project_id, environment_id, len(items), now, browser_type, resolution,
             1 if headless else 0, 1 if capture_requests else 0),
```

(Adjust the literal status/placeholder count to match whatever the real statement looks like at edit time — the point is one new column, one new placeholder, one new bound value, appended at the end.)

At line 555, alongside `child_env["QACLAN_HEADLESS"] = "1" if headless else "0"`:

```python
                child_env["QACLAN_CAPTURE_REQUESTS"] = "1" if capture_requests else "0"
```

Add `sr.capture_requests` to the `get_run()` select list at line 151, alongside `sr.headless`.

- [ ] **Step 2: `scripts.py` — hardcode off for the solo-run path**

In `run_script_solo`, alongside wherever `QACLAN_HEADLESS` is set on `child_env` (this function builds its own env dict inline rather than calling `execute_run`):

```python
        child_env["QACLAN_CAPTURE_REQUESTS"] = "0"
```

No request-body param added here — per spec Section 0, the solo quick-run path has no options UI at all and stays capture-off. A comment should note why, so a future editor doesn't assume this was an oversight:

```python
        # Solo quick-run has no options UI (browser/resolution/headless are also
        # hardcoded here) — capture is opt-in via the suite-run modal only.
        # See docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md Section 0.
        child_env["QACLAN_CAPTURE_REQUESTS"] = "0"
```

- [ ] **Step 3: Verify the env var reaches the child process**

```bash
python3 -c "
import re
runs_src = open('web/routes/runs.py').read()
scripts_src = open('web/routes/scripts.py').read()
assert 'QACLAN_CAPTURE_REQUESTS' in runs_src, 'runs.py missing QACLAN_CAPTURE_REQUESTS'
assert 'QACLAN_CAPTURE_REQUESTS' in scripts_src, 'scripts.py missing QACLAN_CAPTURE_REQUESTS'
assert 'capture_requests' in runs_src, 'runs.py missing capture_requests param/column'
print('OK: both run call sites set QACLAN_CAPTURE_REQUESTS')
"
```

- [ ] **Step 4: Add the checkbox to `app.js`'s suite-run modal**

Alongside the existing `run-headless`/`run-stop-on-fail` checkboxes (~line 3990-3998):

```js
      <label class="checkbox-wrap">
        <input type="checkbox" id="run-capture-requests">
        Capture API Requests
      </label>
```

Alongside where `headless` is read and posted (~line 4006/4017):

```js
      const capture_requests = document.getElementById('run-capture-requests').checked
      // ...
      const res = await api('POST', '/runs', { suite_id: id, env_name, stop_on_fail, browser, resolution, headless, capture_requests, wait_timeout })
```

Unchecked by default (no `checked` attribute) — matches the spec's off-by-default decision.

- [ ] **Step 5: Syntax-check and manual verification**

Run: `node --check web/static/app.js` — expect exit code 0.

Run: `python qaclan.py serve --port 7823`. Open a suite's "Run Suite" modal, confirm "Capture API Requests" appears unchecked alongside Headless/Stop on first failure. Run once with it unchecked, once checked; after each, inspect the DB:

```bash
python3 -c "
from cli.db import get_conn
conn = get_conn()
row = conn.execute('SELECT capture_requests FROM suite_runs ORDER BY started_at DESC LIMIT 1').fetchone()
print('capture_requests:', row['capture_requests'])
"
```

Expected: `0` after the unchecked run, `1` after the checked run.

- [ ] **Step 6: Commit**

```bash
git add web/routes/runs.py web/routes/scripts.py web/static/app.js
git commit -m "feat(runs): add opt-in Capture API Requests checkbox, wire QACLAN_CAPTURE_REQUESTS to both run call sites"
```

---

## Task 2: `captured_request_parser.py` — redact/shape adapter

**Files:**
- Create: `cli/api_discovery/captured_request_parser.py`

**Interfaces:**
- Consumes: raw harness capture dicts, spec shape — `{method, url, request_headers: dict, request_body: str|None, status_code: int|None, response_headers: dict, response_body: str|None, duration_ms: int|None}` (one per entry, see spec Section 1 JSON example).
- Consumes internally: `cli.api_discovery.har_parser.parse_har(har_json: dict) -> list[dict]` (existing, unchanged).
- Produces: `parse_captured_requests(captured: list[dict]) -> list[dict]`, returning the exact `parse_har()` output shape — consumed by Task 7 (`runs.py`).

- [ ] **Step 1: Write the failing test**

```bash
cat > /tmp/qaclan_plan_verify/test_adapter.py <<'EOF'
import sys, os
sys.path.insert(0, os.path.abspath("."))
from cli.api_discovery.captured_request_parser import parse_captured_requests

raw = [
    {
        "method": "POST",
        "url": "https://staging.app.com/api/auth/login?debug=1",
        "request_headers": {"content-type": "application/json", "authorization": "Bearer abc123"},
        "request_body": '{"email":"test@x.com","password":"hunter2"}',
        "status_code": 200,
        "response_headers": {"content-type": "application/json"},
        "response_body": '{"token":"eyJabc"}',
        "duration_ms": 142,
    },
]

out = parse_captured_requests(raw)
assert len(out) == 1, out
r = out[0]
assert r["method"] == "POST"
assert r["url"] == "https://staging.app.com/api/auth/login"  # query stripped into params
assert r["response_status"] == 200
assert r["duration_ms"] == 142
assert r["response_body"] == '{"token":"eyJabc"}'

# authorization header redacted
auth_header = next(h for h in r["headers"] if h["key"].lower() == "authorization")
assert auth_header["value"] == "{{AUTHORIZATION}}", auth_header

# query param preserved and split out
debug_param = next(p for p in r["params"] if p["key"] == "debug")
assert debug_param["value"] == "1", debug_param

# password field inside JSON body is NOT redacted (redaction only applies to
# key/value pairs har_parser can see as discrete fields — headers/params/form
# fields — not to opaque JSON body text; this matches existing HAR-import
# behavior, not a regression introduced here)
assert "hunter2" in r["body"]

print("OK: parse_captured_requests redacts headers/params and preserves shape")
EOF
python3 /tmp/qaclan_plan_verify/test_adapter.py
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/qaclan_plan_verify/test_adapter.py`
Expected: `ModuleNotFoundError: No module named 'cli.api_discovery.captured_request_parser'`

- [ ] **Step 3: Implement the adapter**

```python
"""Converts harness-captured requests (script-run capture, see
docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) into the
exact shape cli.api_discovery.har_parser.parse_har() produces — reusing its
sensitive-value redaction, browser-header skip-list, query-param splitting,
and request/response schema inference instead of duplicating any of it.
"""

from __future__ import annotations

from urllib.parse import urlsplit, parse_qsl

from cli.api_discovery.har_parser import parse_har


def _content_type(headers: dict | None) -> str:
    for k, v in (headers or {}).items():
        if k.lower() == "content-type":
            return v
    return ""


def _to_har_entry(captured: dict) -> dict:
    url = captured.get("url", "")
    query = urlsplit(url).query
    query_string = [
        {"name": k, "value": v}
        for k, v in parse_qsl(query, keep_blank_values=True)
    ]
    req_headers = captured.get("request_headers") or {}
    resp_headers = captured.get("response_headers") or {}

    post_data = {}
    if captured.get("request_body"):
        post_data = {
            "mimeType": _content_type(req_headers),
            "text": captured["request_body"],
        }

    return {
        # Marks this as an XHR/fetch entry so parse_har()'s _should_skip()
        # never filters it out — the harness already filtered at capture time.
        "_resourceType": "fetch",
        "time": captured.get("duration_ms") or 0,
        "request": {
            "method": captured.get("method", "GET"),
            "url": url,
            "headers": [{"name": k, "value": v} for k, v in req_headers.items()],
            "queryString": query_string,
            "postData": post_data,
        },
        "response": {
            "status": captured.get("status_code"),
            "headers": [{"name": k, "value": v} for k, v in resp_headers.items()],
            "content": {
                "mimeType": _content_type(resp_headers),
                "text": captured.get("response_body") or "",
            },
        },
    }


def parse_captured_requests(captured: list[dict]) -> list[dict]:
    """Redact + shape-convert raw harness capture entries by routing them
    through parse_har() — the same redaction/parsing HAR import and Record
    APIs mode already use, so results are indistinguishable from those paths
    to every downstream consumer (request-review-modal.js, save-requests,
    group-requests, save-library)."""
    if not captured:
        return []
    entries = [_to_har_entry(c) for c in captured]
    return parse_har({"log": {"entries": entries}})
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python3 /tmp/qaclan_plan_verify/test_adapter.py`
Expected: `OK: parse_captured_requests redacts headers/params and preserves shape`

- [ ] **Step 5: Commit**

```bash
git add cli/api_discovery/captured_request_parser.py
git commit -m "feat(api-discovery): add captured-request-to-HAR-shape adapter"
```

---

## Task 3: Python harness capture

**Files:**
- Modify: `cli/script_strategies/python_strategy.py:75-90` (`_write_artifacts`), `:110-129` (`_track_network`), `:389-394` (scaffold collision list)

**Interfaces:**
- Produces: `captured_requests` key in the JSON written to `QACLAN_ARTIFACTS_PATH`, consumed by Task 7 (`runs.py`'s extended `_read_artifacts`).
- Consumes: `QACLAN_CAPTURE_REQUESTS` env var (Task 1.5) — the capture branch is a no-op unless it's `"1"`.

- [ ] **Step 1: Write the failing verification script**

```bash
cat > /tmp/qaclan_plan_verify/test_python_harness.py <<'EOF'
import http.server, json, os, socketserver, subprocess, sys, tempfile, threading
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))
from cli.script_strategies.python_strategy import PythonStrategy

# --- local fixture server: one static page that fires one fetch() ---
fixture_dir = Path(tempfile.mkdtemp()) / "fixture"
fixture_dir.mkdir(parents=True)
(fixture_dir / "index.html").write_text(
    '<script>fetch("/data.json").then(r => r.json())</script>', encoding="utf-8"
)
(fixture_dir / "data.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(fixture_dir), **kw)
    def log_message(self, *a):
        pass

httpd = socketserver.TCPServer(("127.0.0.1", 8934), _Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

# --- render + run the harness ---
strategy = PythonStrategy()
actions = 'page.goto("http://127.0.0.1:8934/index.html")\npage.wait_for_timeout(1500)'
rendered = strategy._render_harness(actions)

script_path = Path(tempfile.mktemp(suffix=".py"))
script_path.write_text(rendered, encoding="utf-8")
artifacts_path = Path(tempfile.mktemp(suffix=".json"))

runtime_dir = Path.home() / ".qaclan" / "runtime"
env = os.environ.copy()
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
env["QACLAN_HEADLESS"] = "1"
env["QACLAN_BROWSER"] = "chromium"
env["QACLAN_CAPTURE_REQUESTS"] = "1"  # opt-in flag — must be set or the capture branch never runs
env["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime_dir / "browsers")

result = subprocess.run(
    [str(runtime_dir / "venv" / "bin" / "python"), str(script_path)],
    env=env, capture_output=True, text=True, timeout=30,
)
assert result.returncode == 0, f"harness failed: {result.stdout}\n{result.stderr}"

data = json.loads(artifacts_path.read_text())
assert "captured_requests" in data, f"no captured_requests key: {data.keys()}"
captured = data["captured_requests"]
matches = [c for c in captured if c["url"].endswith("/data.json")]
assert matches, f"data.json fetch not captured: {captured}"
entry = matches[0]
assert entry["method"] == "GET"
assert entry["status_code"] == 200
assert entry["duration_ms"] is not None
assert '"ok": true' in entry["response_body"].lower()
print("OK: python harness captured the fetch() call")

# --- confirm the opt-in gate actually gates: capture OFF must yield an empty list ---
# (fixture server stays up for this run — only shut down after, so the gate is
# proven by the flag, not by the fetch having nothing to hit)
env["QACLAN_CAPTURE_REQUESTS"] = "0"
artifacts_path_off = Path(tempfile.mktemp(suffix=".json"))
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path_off)
result_off = subprocess.run(
    [str(runtime_dir / "venv" / "bin" / "python"), str(script_path)],
    env=env, capture_output=True, text=True, timeout=30,
)
httpd.shutdown()
assert result_off.returncode == 0, f"harness failed (capture off): {result_off.stdout}\n{result_off.stderr}"
data_off = json.loads(artifacts_path_off.read_text())
assert data_off.get("captured_requests") == [], f"capture ran despite QACLAN_CAPTURE_REQUESTS=0: {data_off['captured_requests']}"
print("OK: python harness does not capture when QACLAN_CAPTURE_REQUESTS=0")
EOF
python3 /tmp/qaclan_plan_verify/test_python_harness.py
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/qaclan_plan_verify/test_python_harness.py`
Expected: `AssertionError: no captured_requests key: dict_keys(['console_errors', 'network_failures'])`

- [ ] **Step 3: Implement the capture**

In `cli/script_strategies/python_strategy.py`, replace the `_track_network` block (lines 110-129):

```python
# --- Smart-wait network tracking (docs/auto-wait-plan.md) ---
# Counts in-flight XHR/fetch requests so _wait_for_network_settle can block
# until a slow-loading page (table fed by an XHR) finishes.
_in_flight = 0

# --- Request capture (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) ---
# Records XHR/fetch traffic as a passive side effect of the run so it can be
# saved as API requests afterward. Never fails the run — every capture step
# is wrapped in a swallowed try/except. Opt-in: off unless QACLAN_CAPTURE_REQUESTS=1,
# checked once at startup so _capture_request() no-ops before touching anything
# when the run didn't ask for capture.
_CAPTURE_ENABLED = os.environ.get("QACLAN_CAPTURE_REQUESTS") == "1"
_captured_requests = []
_capture_starts = {}
_CAPTURE_CAP = 200
_CAPTURE_BODY_CAP_BYTES = 200_000
_CAPTURE_SKIP_TYPES = {"document", "stylesheet", "image", "font", "script"}


def _truncate_body(text):
    if text is None:
        return None
    encoded = text.encode("utf-8", errors="ignore")
    if len(encoded) <= _CAPTURE_BODY_CAP_BYTES:
        return text
    return encoded[:_CAPTURE_BODY_CAP_BYTES].decode("utf-8", errors="ignore")


def _capture_request(req):
    if not _CAPTURE_ENABLED:
        return
    if req.resource_type in _CAPTURE_SKIP_TYPES:
        return
    start = _capture_starts.pop(id(req), None)
    if len(_captured_requests) >= _CAPTURE_CAP:
        return
    try:
        duration_ms = int((time.monotonic() - start) * 1000) if start is not None else None
        resp = None
        try:
            resp = req.response()
        except Exception:
            resp = None
        entry = {
            "method": req.method,
            "url": req.url,
            "request_headers": dict(req.headers),
            "request_body": _truncate_body(req.post_data),
            "status_code": resp.status if resp else None,
            "response_headers": dict(resp.headers) if resp else {},
            "response_body": None,
            "duration_ms": duration_ms,
        }
        if resp is not None:
            try:
                entry["response_body"] = _truncate_body(resp.text())
            except Exception:
                pass
        _captured_requests.append(entry)
    except Exception:
        pass


def _track_network(page):
    def _on_request(req):
        global _in_flight
        if req.resource_type in ("xhr", "fetch"):
            _in_flight += 1
        if _CAPTURE_ENABLED and req.resource_type not in _CAPTURE_SKIP_TYPES:
            _capture_starts[id(req)] = time.monotonic()

    def _on_done(req):
        global _in_flight
        if req.resource_type in ("xhr", "fetch"):
            _in_flight = max(0, _in_flight - 1)
        _capture_request(req)

    page.on("request", _on_request)
    page.on("requestfinished", _on_done)
    page.on("requestfailed", _on_done)
```

`os` is already imported at the top of the rendered harness (used elsewhere for env var reads like `QACLAN_HEADLESS`) — no new import needed.

Then extend `_write_artifacts` (lines 75-90) to include the capture buffer:

```python
def _write_artifacts(error=None):
    if not _ARTIFACTS:
        return
    try:
        payload = {
            "console_errors": _console_errors,
            "network_failures": _network_failures,
            "captured_requests": _captured_requests,
        }
        # Structured error — raw exception fields the runner's classifier
        # keys on. See docs/error-reporting-plan.md (section 2.1).
        if error is not None:
            payload["error"] = error
        with open(_ARTIFACTS, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except Exception:
        pass
```

Finally, extend the scaffold collision list (lines 389-394) so an action body can't accidentally clobber the new module-level names:

```python
        for name in (
            "_BROWSER", "_HEADLESS", "_VIEWPORT", "_STATE", "_ARTIFACTS",
            "_SCREENSHOT", "_console_errors", "_network_failures", "_context_opts",
            "_write_artifacts", "_on_console", "_on_pageerror", "_on_requestfailed",
            "_in_flight", "_captured_requests", "_capture_starts", "_capture_request",
            "_CAPTURE_ENABLED", "_CAPTURE_CAP", "_CAPTURE_BODY_CAP_BYTES",
            "_CAPTURE_SKIP_TYPES", "_truncate_body",
        ):
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python3 /tmp/qaclan_plan_verify/test_python_harness.py`
Expected both lines print:
```
OK: python harness captured the fetch() call
OK: python harness does not capture when QACLAN_CAPTURE_REQUESTS=0
```

- [ ] **Step 5: Commit**

```bash
git add cli/script_strategies/python_strategy.py
git commit -m "feat(harness): capture XHR/fetch traffic in the Python strategy"
```

---

## Task 4: JavaScript harness capture

**Files:**
- Modify: `cli/script_strategies/javascript_strategy.py:43-61` (`_trackNetwork`), `:105-117` (`_writeArtifacts`), `:142-156` (`run()`'s `finally`), `:173-177` (`_QACLAN_JS_NAMES`)

**Interfaces:**
- Produces: `captured_requests` key in the JSON written to `QACLAN_ARTIFACTS_PATH`, same shape as Task 3.
- Consumes: `QACLAN_CAPTURE_REQUESTS` env var (Task 1.5) — same gate as Task 3.
- Note: unlike Python's fully-synchronous `sync_playwright` API, JS event handlers are not awaited by Playwright — `_captureRequest` is async, so every call is pushed onto a `_capturePending` array and awaited with `Promise.allSettled` before `run()` returns, otherwise the last in-flight capture could race the process exit and never make it into `_capturedRequests`.

- [ ] **Step 1: Write the failing verification script**

```bash
cat > /tmp/qaclan_plan_verify/test_js_harness.py <<'EOF'
import http.server, json, os, socketserver, subprocess, sys, tempfile, threading
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))
from cli.script_strategies.javascript_strategy import JavaScriptStrategy

fixture_dir = Path(tempfile.mkdtemp()) / "fixture"
fixture_dir.mkdir(parents=True)
(fixture_dir / "index.html").write_text(
    '<script>fetch("/data.json").then(r => r.json())</script>', encoding="utf-8"
)
(fixture_dir / "data.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(fixture_dir), **kw)
    def log_message(self, *a):
        pass

httpd = socketserver.TCPServer(("127.0.0.1", 8935), _Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

strategy = JavaScriptStrategy()
actions = 'await page.goto("http://127.0.0.1:8935/index.html");\nawait page.waitForTimeout(1500);'
rendered = strategy._render_harness(actions)

script_path = Path(tempfile.mktemp(suffix=".js"))
script_path.write_text(rendered, encoding="utf-8")
artifacts_path = Path(tempfile.mktemp(suffix=".json"))

runtime_dir = Path.home() / ".qaclan" / "runtime"
env = os.environ.copy()
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
env["QACLAN_HEADLESS"] = "1"
env["QACLAN_BROWSER"] = "chromium"
env["QACLAN_CAPTURE_REQUESTS"] = "1"  # opt-in flag — must be set or the capture branch never runs
env["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime_dir / "browsers")
env["NODE_PATH"] = str(runtime_dir / "node_modules")

result = subprocess.run(
    ["node", str(script_path)], env=env, capture_output=True, text=True, timeout=30,
)
assert result.returncode == 0, f"harness failed: {result.stdout}\n{result.stderr}"

data = json.loads(artifacts_path.read_text())
assert "captured_requests" in data, f"no captured_requests key: {data.keys()}"
matches = [c for c in data["captured_requests"] if c["url"].endswith("/data.json")]
assert matches, f"data.json fetch not captured: {data['captured_requests']}"
entry = matches[0]
assert entry["method"] == "GET"
assert entry["status_code"] == 200
assert entry["duration_ms"] is not None
assert '"ok": true' in entry["response_body"].lower()
print("OK: javascript harness captured the fetch() call")

# --- confirm the opt-in gate actually gates ---
env["QACLAN_CAPTURE_REQUESTS"] = "0"
artifacts_path_off = Path(tempfile.mktemp(suffix=".json"))
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path_off)
result_off = subprocess.run(
    ["node", str(script_path)], env=env, capture_output=True, text=True, timeout=30,
)
httpd.shutdown()
assert result_off.returncode == 0, f"harness failed (capture off): {result_off.stdout}\n{result_off.stderr}"
data_off = json.loads(artifacts_path_off.read_text())
assert data_off.get("captured_requests") == [], f"capture ran despite QACLAN_CAPTURE_REQUESTS=0: {data_off['captured_requests']}"
print("OK: javascript harness does not capture when QACLAN_CAPTURE_REQUESTS=0")
EOF
python3 /tmp/qaclan_plan_verify/test_js_harness.py
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/qaclan_plan_verify/test_js_harness.py`
Expected: `AssertionError: no captured_requests key: dict_keys(['console_errors', 'network_failures'])`

- [ ] **Step 3: Implement the capture**

In `cli/script_strategies/javascript_strategy.py`, replace the `_trackNetwork` block (lines 46-61):

```js
// --- Smart-wait network tracking (docs/auto-wait-plan.md) ---
// Counts in-flight XHR/fetch requests so _waitForNetworkSettle can block
// until a slow-loading page (table fed by an XHR) finishes.
let _inFlight = 0;

// --- Request capture (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) ---
// Records XHR/fetch traffic as a passive side effect of the run so it can be
// saved as API requests afterward. Never fails the run — every capture step
// is wrapped in a try/catch that swallows errors. Playwright does not await
// page.on() handlers, so every _captureRequest() call is tracked in
// _capturePending and awaited before run() returns (see the finally block
// below) — otherwise the last in-flight capture can race process exit.
// Opt-in: off unless QACLAN_CAPTURE_REQUESTS=1, checked once at startup.
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests = [];
const _captureStarts = new Map();
const _capturePending = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_SKIP_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script']);

function _truncateBody(text) {
  if (text == null) return text;
  const buf = Buffer.from(text, 'utf-8');
  if (buf.length <= _CAPTURE_BODY_CAP_BYTES) return text;
  return buf.subarray(0, _CAPTURE_BODY_CAP_BYTES).toString('utf-8');
}

async function _captureRequest(req) {
  if (!_CAPTURE_ENABLED) return;
  if (_CAPTURE_SKIP_TYPES.has(req.resourceType())) return;
  const start = _captureStarts.get(req);
  _captureStarts.delete(req);
  if (_capturedRequests.length >= _CAPTURE_CAP) return;
  try {
    const resp = await req.response();
    const entry = {
      method: req.method(),
      url: req.url(),
      request_headers: await req.allHeaders(),
      request_body: _truncateBody(req.postData()),
      status_code: resp ? resp.status() : null,
      response_headers: resp ? await resp.allHeaders() : {},
      response_body: null,
      duration_ms: start != null ? Date.now() - start : null,
    };
    if (resp) {
      try { entry.response_body = _truncateBody(await resp.text()); } catch (_) {}
    }
    _capturedRequests.push(entry);
  } catch (_) {}
}

function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && !_CAPTURE_SKIP_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
  const done = req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight = Math.max(0, _inFlight - 1);
    _capturePending.push(_captureRequest(req).catch(() => {}));
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
}
```

Extend `_writeArtifacts` (lines 105-117):

```js
function _writeArtifacts(error) {
  if (!_ARTIFACTS) return;
  try {
    const payload = {
      console_errors: _consoleErrors,
      network_failures: _networkFailures,
      captured_requests: _capturedRequests,
    };
    // Structured error — raw exception fields the runner's classifier keys
    // on. See docs/error-reporting-plan.md (section 2.1).
    if (error) payload.error = error;
    fs.writeFileSync(_ARTIFACTS, JSON.stringify(payload));
  } catch (_) {}
}
```

Await pending captures in `run()`'s `finally` block (lines 149-156) before it returns:

```js
  } finally {
    await Promise.allSettled(_capturePending);
    if (_STATE) {
      try { await context.storageState({ path: _STATE }); } catch (_) {}
    }
    try { await page.close(); } catch (_) {}
    try { await context.close(); } catch (_) {}
    try { await browser.close(); } catch (_) {}
  }
```

Extend the shared collision list (lines 173-177) — this same tuple is imported and reused by `javascript_test_strategy.py`'s `_js_body_warnings()` (Task 5), so this one edit covers JS, JS-test, and TS (inherited):

```python
_QACLAN_JS_NAMES = (
    "_BROWSER", "_HEADLESS", "_VIEWPORT", "_STATE", "_ARTIFACTS",
    "_SCREENSHOT", "_consoleErrors", "_networkFailures", "_contextOpts",
    "_writeArtifacts", "_browsers", "_browserType", "_inFlight",
    "_capturedRequests", "_captureStarts", "_capturePending",
    "_CAPTURE_ENABLED", "_CAPTURE_CAP", "_CAPTURE_BODY_CAP_BYTES",
    "_CAPTURE_SKIP_TYPES", "_truncateBody",
)
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python3 /tmp/qaclan_plan_verify/test_js_harness.py`
Expected both lines print:
```
OK: javascript harness captured the fetch() call
OK: javascript harness does not capture when QACLAN_CAPTURE_REQUESTS=0
```

- [ ] **Step 5: Commit**

```bash
git add cli/script_strategies/javascript_strategy.py
git commit -m "feat(harness): capture XHR/fetch traffic in the JavaScript strategy"
```

---

## Task 5: JavaScript-test (`@playwright/test`) harness capture

**Files:**
- Modify: `cli/script_strategies/javascript_test_strategy.py:45-58` (`_trackNetwork`), `:84-113` (`test('qaclan', ...)` body + `finally`), `:115-128` (`test.afterAll`)

**Interfaces:**
- Produces: same as Task 3/4, including the `QACLAN_CAPTURE_REQUESTS` gate.
- Consumes: `_QACLAN_JS_NAMES` from Task 4 (already covers this file via its existing `_js_body_warnings` import, including the new `_CAPTURE_ENABLED`/`_CAPTURE_BODY_CAP_BYTES`/`_truncateBody` names — no separate collision-list edit needed here).

- [ ] **Step 1: Write the failing verification script**

This strategy needs a `playwright.config.js` alongside the rendered spec file (`setup_run_dir()` normally writes it; for this standalone verification we write a minimal one directly):

```bash
cat > /tmp/qaclan_plan_verify/test_jstest_harness.py <<'EOF'
import http.server, json, os, socketserver, subprocess, sys, tempfile, threading
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))
from cli.script_strategies.javascript_test_strategy import JavaScriptTestStrategy

fixture_dir = Path(tempfile.mkdtemp()) / "fixture"
fixture_dir.mkdir(parents=True)
(fixture_dir / "index.html").write_text(
    '<script>fetch("/data.json").then(r => r.json())</script>', encoding="utf-8"
)
(fixture_dir / "data.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(fixture_dir), **kw)
    def log_message(self, *a):
        pass

httpd = socketserver.TCPServer(("127.0.0.1", 8936), _Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

strategy = JavaScriptTestStrategy()
actions = 'await page.goto("http://127.0.0.1:8936/index.html");\nawait page.waitForTimeout(1500);'
rendered = strategy._render_harness(actions)

run_dir = Path(tempfile.mkdtemp())
script_path = run_dir / "spec.spec.js"
script_path.write_text(rendered, encoding="utf-8")
(run_dir / "playwright.config.js").write_text(
    "module.exports = { use: { headless: true }, reporter: 'list' };", encoding="utf-8"
)
artifacts_path = Path(tempfile.mktemp(suffix=".json"))

runtime_dir = Path.home() / ".qaclan" / "runtime"
env = os.environ.copy()
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
env["QACLAN_CAPTURE_REQUESTS"] = "1"  # opt-in flag — must be set or the capture branch never runs
env["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime_dir / "browsers")
env["NODE_PATH"] = str(runtime_dir / "node_modules")

result = subprocess.run(
    ["npx", "playwright", "test", str(script_path), "--config", str(run_dir / "playwright.config.js")],
    env=env, capture_output=True, text=True, timeout=60, cwd=str(runtime_dir),
)
assert result.returncode == 0, f"harness failed: {result.stdout}\n{result.stderr}"

data = json.loads(artifacts_path.read_text())
assert "captured_requests" in data, f"no captured_requests key: {data.keys()}"
matches = [c for c in data["captured_requests"] if c["url"].endswith("/data.json")]
assert matches, f"data.json fetch not captured: {data['captured_requests']}"
entry = matches[0]
assert entry["method"] == "GET"
assert entry["status_code"] == 200
print("OK: javascript_test harness captured the fetch() call")

# --- confirm the opt-in gate actually gates ---
env["QACLAN_CAPTURE_REQUESTS"] = "0"
artifacts_path_off = Path(tempfile.mktemp(suffix=".json"))
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path_off)
result_off = subprocess.run(
    ["npx", "playwright", "test", str(script_path), "--config", str(run_dir / "playwright.config.js")],
    env=env, capture_output=True, text=True, timeout=60, cwd=str(runtime_dir),
)
httpd.shutdown()
assert result_off.returncode == 0, f"harness failed (capture off): {result_off.stdout}\n{result_off.stderr}"
data_off = json.loads(artifacts_path_off.read_text())
assert data_off.get("captured_requests") == [], f"capture ran despite QACLAN_CAPTURE_REQUESTS=0: {data_off['captured_requests']}"
print("OK: javascript_test harness does not capture when QACLAN_CAPTURE_REQUESTS=0")
EOF
python3 /tmp/qaclan_plan_verify/test_jstest_harness.py
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/qaclan_plan_verify/test_jstest_harness.py`
Expected: `AssertionError: no captured_requests key: dict_keys(['console_errors', 'network_failures'])`

- [ ] **Step 3: Implement the capture**

Replace the `_trackNetwork` block (lines 45-58):

```js
// --- Smart-wait network tracking (docs/auto-wait-plan.md) ---
let _inFlight = 0;

// --- Request capture (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) ---
// See javascript_strategy.py for the race-safety rationale on _capturePending.
// Opt-in: off unless QACLAN_CAPTURE_REQUESTS=1, checked once at startup.
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests = [];
const _captureStarts = new Map();
const _capturePending = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_SKIP_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script']);

function _truncateBody(text) {
  if (text == null) return text;
  const buf = Buffer.from(text, 'utf-8');
  if (buf.length <= _CAPTURE_BODY_CAP_BYTES) return text;
  return buf.subarray(0, _CAPTURE_BODY_CAP_BYTES).toString('utf-8');
}

async function _captureRequest(req) {
  if (!_CAPTURE_ENABLED) return;
  if (_CAPTURE_SKIP_TYPES.has(req.resourceType())) return;
  const start = _captureStarts.get(req);
  _captureStarts.delete(req);
  if (_capturedRequests.length >= _CAPTURE_CAP) return;
  try {
    const resp = await req.response();
    const entry = {
      method: req.method(),
      url: req.url(),
      request_headers: await req.allHeaders(),
      request_body: _truncateBody(req.postData()),
      status_code: resp ? resp.status() : null,
      response_headers: resp ? await resp.allHeaders() : {},
      response_body: null,
      duration_ms: start != null ? Date.now() - start : null,
    };
    if (resp) {
      try { entry.response_body = _truncateBody(await resp.text()); } catch (_) {}
    }
    _capturedRequests.push(entry);
  } catch (_) {}
}

function _trackNetwork(page) {
  page.on('request', req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && !_CAPTURE_SKIP_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
  const done = req => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight = Math.max(0, _inFlight - 1);
    _capturePending.push(_captureRequest(req).catch(() => {}));
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
}
```

Await pending captures in the `test('qaclan', ...)` body's `finally` (lines 108-112):

```js
  } finally {
    await Promise.allSettled(_capturePending);
    if (_STATE) {
      try { await context.storageState({ path: _STATE }); } catch (_) {}
    }
  }
```

Extend `test.afterAll` (lines 115-128):

```js
test.afterAll(() => {
  if (!_ARTIFACTS) return;
  try {
    const payload = {
      console_errors: _consoleErrors,
      network_failures: _networkFailures,
      captured_requests: _capturedRequests,
    };
    if (_scriptError) payload.error = {
      raw_type: (_scriptError && _scriptError.name) || 'Error',
      raw_message: (_scriptError && _scriptError.message) || String(_scriptError),
    };
    fs.writeFileSync(_ARTIFACTS, JSON.stringify(payload));
  } catch (_) {}
});
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python3 /tmp/qaclan_plan_verify/test_jstest_harness.py`
Expected both lines print:
```
OK: javascript_test harness captured the fetch() call
OK: javascript_test harness does not capture when QACLAN_CAPTURE_REQUESTS=0
```

- [ ] **Step 5: Commit**

```bash
git add cli/script_strategies/javascript_test_strategy.py
git commit -m "feat(harness): capture XHR/fetch traffic in the JavaScript-test strategy"
```

---

## Task 6: TypeScript-test harness capture

**Files:**
- Modify: `cli/script_strategies/typescript_test_strategy.py:37-50` (`_trackNetwork`), `:76-105` (`test('qaclan', ...)` body + `finally`), `:107-120` (`test.afterAll`)

**Interfaces:**
- Produces: same as Task 3/4/5, including the `QACLAN_CAPTURE_REQUESTS` gate. This is the last harness template — `typescript_strategy.py` (non-test TS) needs no edit, it inherits `javascript_strategy.py`'s already-capturing template.

- [ ] **Step 1: Write the failing verification script**

```bash
cat > /tmp/qaclan_plan_verify/test_tstest_harness.py <<'EOF'
import http.server, json, os, socketserver, subprocess, sys, tempfile, threading
from pathlib import Path

sys.path.insert(0, os.path.abspath("."))
from cli.script_strategies.typescript_test_strategy import TypeScriptTestStrategy

fixture_dir = Path(tempfile.mkdtemp()) / "fixture"
fixture_dir.mkdir(parents=True)
(fixture_dir / "index.html").write_text(
    '<script>fetch("/data.json").then(r => r.json())</script>', encoding="utf-8"
)
(fixture_dir / "data.json").write_text(json.dumps({"ok": True}), encoding="utf-8")

class _Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(fixture_dir), **kw)
    def log_message(self, *a):
        pass

httpd = socketserver.TCPServer(("127.0.0.1", 8937), _Handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()

strategy = TypeScriptTestStrategy()
actions = 'await page.goto("http://127.0.0.1:8937/index.html");\nawait page.waitForTimeout(1500);'
rendered = strategy._render_harness(actions)

run_dir = Path(tempfile.mkdtemp())
script_path = run_dir / "spec.spec.ts"
script_path.write_text(rendered, encoding="utf-8")
(run_dir / "playwright.config.js").write_text(
    "module.exports = { use: { headless: true }, reporter: 'list' };", encoding="utf-8"
)
artifacts_path = Path(tempfile.mktemp(suffix=".json"))

runtime_dir = Path.home() / ".qaclan" / "runtime"
env = os.environ.copy()
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path)
env["QACLAN_CAPTURE_REQUESTS"] = "1"  # opt-in flag — must be set or the capture branch never runs
env["PLAYWRIGHT_BROWSERS_PATH"] = str(runtime_dir / "browsers")
env["NODE_PATH"] = str(runtime_dir / "node_modules")

result = subprocess.run(
    ["npx", "playwright", "test", str(script_path), "--config", str(run_dir / "playwright.config.js")],
    env=env, capture_output=True, text=True, timeout=60, cwd=str(runtime_dir),
)
assert result.returncode == 0, f"harness failed: {result.stdout}\n{result.stderr}"

data = json.loads(artifacts_path.read_text())
assert "captured_requests" in data, f"no captured_requests key: {data.keys()}"
matches = [c for c in data["captured_requests"] if c["url"].endswith("/data.json")]
assert matches, f"data.json fetch not captured: {data['captured_requests']}"
entry = matches[0]
assert entry["method"] == "GET"
assert entry["status_code"] == 200
print("OK: typescript_test harness captured the fetch() call")

# --- confirm the opt-in gate actually gates ---
env["QACLAN_CAPTURE_REQUESTS"] = "0"
artifacts_path_off = Path(tempfile.mktemp(suffix=".json"))
env["QACLAN_ARTIFACTS_PATH"] = str(artifacts_path_off)
result_off = subprocess.run(
    ["npx", "playwright", "test", str(script_path), "--config", str(run_dir / "playwright.config.js")],
    env=env, capture_output=True, text=True, timeout=60, cwd=str(runtime_dir),
)
httpd.shutdown()
assert result_off.returncode == 0, f"harness failed (capture off): {result_off.stdout}\n{result_off.stderr}"
data_off = json.loads(artifacts_path_off.read_text())
assert data_off.get("captured_requests") == [], f"capture ran despite QACLAN_CAPTURE_REQUESTS=0: {data_off['captured_requests']}"
print("OK: typescript_test harness does not capture when QACLAN_CAPTURE_REQUESTS=0")
EOF
python3 /tmp/qaclan_plan_verify/test_tstest_harness.py
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `python3 /tmp/qaclan_plan_verify/test_tstest_harness.py`
Expected: `AssertionError: no captured_requests key: dict_keys(['console_errors', 'network_failures'])`

- [ ] **Step 3: Implement the capture**

Replace the `_trackNetwork` block (lines 37-50):

```ts
// --- Smart-wait network tracking (docs/auto-wait-plan.md) ---
let _inFlight = 0;

// --- Request capture (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md) ---
// See javascript_strategy.py for the race-safety rationale on _capturePending.
// Opt-in: off unless QACLAN_CAPTURE_REQUESTS=1, checked once at startup.
const _CAPTURE_ENABLED = process.env.QACLAN_CAPTURE_REQUESTS === '1';
const _capturedRequests: Array<{
  method: string;
  url: string;
  request_headers: Record<string, string>;
  request_body: string | null;
  status_code: number | null;
  response_headers: Record<string, string>;
  response_body: string | null;
  duration_ms: number | null;
}> = [];
const _captureStarts = new Map<any, number>();
const _capturePending: Promise<void>[] = [];
const _CAPTURE_CAP = 200;
const _CAPTURE_BODY_CAP_BYTES = 200000;
const _CAPTURE_SKIP_TYPES = new Set(['document', 'stylesheet', 'image', 'font', 'script']);

function _truncateBody(text: string | null): string | null {
  if (text == null) return text;
  const buf = Buffer.from(text, 'utf-8');
  if (buf.length <= _CAPTURE_BODY_CAP_BYTES) return text;
  return buf.subarray(0, _CAPTURE_BODY_CAP_BYTES).toString('utf-8');
}

async function _captureRequest(req: any): Promise<void> {
  if (!_CAPTURE_ENABLED) return;
  if (_CAPTURE_SKIP_TYPES.has(req.resourceType())) return;
  const start = _captureStarts.get(req);
  _captureStarts.delete(req);
  if (_capturedRequests.length >= _CAPTURE_CAP) return;
  try {
    const resp = await req.response();
    const entry = {
      method: req.method(),
      url: req.url(),
      request_headers: await req.allHeaders(),
      request_body: _truncateBody(req.postData()),
      status_code: resp ? resp.status() : null,
      response_headers: resp ? await resp.allHeaders() : {},
      response_body: null as string | null,
      duration_ms: start != null ? Date.now() - start : null,
    };
    if (resp) {
      try { entry.response_body = _truncateBody(await resp.text()); } catch (_) {}
    }
    _capturedRequests.push(entry);
  } catch (_) {}
}

function _trackNetwork(page: any) {
  page.on('request', (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight++;
    if (_CAPTURE_ENABLED && !_CAPTURE_SKIP_TYPES.has(t)) _captureStarts.set(req, Date.now());
  });
  const done = (req: any) => {
    const t = req.resourceType();
    if (t === 'xhr' || t === 'fetch') _inFlight = Math.max(0, _inFlight - 1);
    _capturePending.push(_captureRequest(req).catch(() => {}));
  };
  page.on('requestfinished', done);
  page.on('requestfailed', done);
}
```

Await pending captures in the `test('qaclan', ...)` body's `finally` (lines 100-104):

```ts
  } finally {
    await Promise.allSettled(_capturePending);
    if (_STATE) {
      try { await context.storageState({ path: _STATE }); } catch (_) {}
    }
  }
```

Extend `test.afterAll` (lines 107-120):

```ts
test.afterAll(() => {
  if (!_ARTIFACTS) return;
  try {
    const payload: any = {
      console_errors: _consoleErrors,
      network_failures: _networkFailures,
      captured_requests: _capturedRequests,
    };
    if (_scriptError) payload.error = {
      raw_type: (_scriptError && _scriptError.name) || 'Error',
      raw_message: (_scriptError && _scriptError.message) || String(_scriptError),
    };
    fs.writeFileSync(_ARTIFACTS, JSON.stringify(payload));
  } catch (_) {}
});
```

- [ ] **Step 4: Run it to confirm it passes**

Run: `python3 /tmp/qaclan_plan_verify/test_tstest_harness.py`
Expected both lines print:
```
OK: typescript_test harness captured the fetch() call
OK: typescript_test harness does not capture when QACLAN_CAPTURE_REQUESTS=0
```

- [ ] **Step 5: Commit**

```bash
git add cli/script_strategies/typescript_test_strategy.py
git commit -m "feat(harness): capture XHR/fetch traffic in the TypeScript-test strategy"
```

---

## Task 7: Wire `web/routes/runs.py` — persist + expose captured requests

**Files:**
- Modify: `web/routes/runs.py:34-53` (`_read_artifacts`), `:161-180` (`get_run` script_rows query/response), `:594` and `:623-648` (success path), `:661` and `:666-690` (timeout path)

**Interfaces:**
- Consumes: `cli.api_discovery.captured_request_parser.parse_captured_requests` (Task 2).
- Consumes: `capture_requests`/`QACLAN_CAPTURE_REQUESTS` wiring already done in Task 1.5 — this task doesn't branch on the flag itself; when it's off, the harness just never populates `captured_requests` in the artifacts JSON, so `_read_artifacts` naturally returns `[]` and `parse_captured_requests([])` short-circuits to `[]` (see Task 2's `if not captured: return []`).
- Produces: `captured_requests` (JSON text, already redacted) and `captured_requests_count` (int) on both the `get_run()` response and the immediate `execute_run()` response, matching how `console_log`/`network_log`/`console_errors`/`network_failures` are already exposed.

- [ ] **Step 1: Add the import**

At the top of `web/routes/runs.py`, alongside the other `cli.*` imports (after line 19, `from cli.script_strategies._shared import substitute_template_vars`):

```python
from cli.api_discovery.captured_request_parser import parse_captured_requests
```

- [ ] **Step 2: Extend `_read_artifacts` to also return the raw capture**

Replace `_read_artifacts` (lines 34-53):

```python
def _read_artifacts(path: Path):
    """Read the artifacts JSON a script writes on exit. Missing or malformed
    files degrade gracefully to empty lists — a crashed script may not have
    written anything.

    Returns (console_errors, network_failures, captured_requests, error) —
    `captured_requests` is the raw (unredacted) harness capture list, `error`
    is the harness's structured exception dict ({raw_type, raw_message}) or
    None.
    """
    if not path.exists():
        return [], [], [], None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return (
            data.get("console_errors", []) or [],
            data.get("network_failures", []) or [],
            data.get("captured_requests", []) or [],
            data.get("error") or None,
        )
    except Exception as e:
        logger.warning("Failed to read artifacts at %s: %s", path, e)
        return [], [], [], None
```

- [ ] **Step 3: Update the success-path call site**

Around line 594, replace:

```python
                console_errors, network_failures, artifacts_error = _read_artifacts(artifacts_path)
```

with:

```python
                console_errors, network_failures, captured_requests_raw, artifacts_error = _read_artifacts(artifacts_path)
                try:
                    captured_requests = parse_captured_requests(captured_requests_raw)
                except Exception:
                    logger.warning("execute_run: failed to parse captured requests for %s", srun_id, exc_info=True)
                    captured_requests = []
```

Then update the `INSERT INTO script_runs` a few lines below (lines 623-634) to persist it:

```python
                error_detail_json = json.dumps(error_detail) if error_detail else None
                captured_requests_json = json.dumps(captured_requests) if captured_requests else None
                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, error_detail, console_errors, network_failures, "
                    "console_log, network_log, screenshot_path, captured_requests, captured_requests_count, "
                    "started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"], status,
                     duration_ms, error_msg, error_detail_json,
                     len(console_errors), len(network_failures),
                     json.dumps(console_errors) if console_errors else None,
                     json.dumps(network_failures) if network_failures else None,
                     saved_screenshot, captured_requests_json, len(captured_requests),
                     script_now, finished_at),
                )
```

And extend the in-memory `script_results.append(...)` right below it (lines 636-648) so the immediate `execute_run()` response also carries it:

```python
                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": status,
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "error_detail": error_detail,
                    "screenshot_path": saved_screenshot,
                    "console_errors": len(console_errors),
                    "network_failures": len(network_failures),
                    "console_log": json.dumps(console_errors) if console_errors else None,
                    "network_log": json.dumps(network_failures) if network_failures else None,
                    "captured_requests": captured_requests_json,
                    "captured_requests_count": len(captured_requests),
                })
```

- [ ] **Step 4: Update the timeout-path call site**

Around line 661, apply the same pattern:

```python
                console_errors, network_failures, captured_requests_raw, artifacts_error = _read_artifacts(artifacts_path)
                try:
                    captured_requests = parse_captured_requests(captured_requests_raw)
                except Exception:
                    logger.warning("execute_run: failed to parse captured requests for %s", srun_id, exc_info=True)
                    captured_requests = []
```

Update the timeout-path `INSERT` (lines 666-677):

```python
                error_detail_json = json.dumps(error_detail)
                captured_requests_json = json.dumps(captured_requests) if captured_requests else None
                conn.execute(
                    "INSERT INTO script_runs (id, suite_run_id, script_id, order_index, status, "
                    "duration_ms, error_message, error_detail, console_errors, network_failures, "
                    "console_log, network_log, screenshot_path, captured_requests, captured_requests_count, "
                    "started_at, finished_at) "
                    "VALUES (?, ?, ?, ?, 'FAILED', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (srun_id, run_id, item["script_id"], item["order_index"],
                     duration_ms, error_msg, error_detail_json,
                     len(console_errors), len(network_failures),
                     json.dumps(console_errors) if console_errors else None,
                     json.dumps(network_failures) if network_failures else None,
                     saved_screenshot, captured_requests_json, len(captured_requests),
                     script_now, finished_at),
                )
```

And the timeout-path `script_results.append(...)` (lines 678-690):

```python
                script_results.append({
                    "script_id": item["script_id"],
                    "name": item["script_name"],
                    "status": "FAILED",
                    "duration_ms": duration_ms,
                    "error_message": error_msg,
                    "error_detail": error_detail,
                    "screenshot_path": saved_screenshot,
                    "console_errors": len(console_errors),
                    "network_failures": len(network_failures),
                    "console_log": json.dumps(console_errors) if console_errors else None,
                    "network_log": json.dumps(network_failures) if network_failures else None,
                    "captured_requests": captured_requests_json,
                    "captured_requests_count": len(captured_requests),
                })
```

- [ ] **Step 5: Expose it in `get_run()`**

Update the `script_rows` query (lines 161-167):

```python
        script_rows = conn.execute(
            "SELECT scr.script_id, s.name, scr.status, scr.duration_ms, "
            "scr.console_errors, scr.network_failures, scr.error_message, scr.error_detail, "
            "scr.console_log, scr.network_log, scr.screenshot_path, "
            "scr.captured_requests, scr.captured_requests_count, "
            "scr.order_index, scr.started_at, scr.finished_at "
            "FROM script_runs scr JOIN scripts s ON scr.script_id = s.id "
            "WHERE scr.suite_run_id = ? ORDER BY scr.order_index",
            (run_id,),
        ).fetchall()
```

No further change needed in the loop below it — `dict(sr)` already carries the two new columns through unchanged, exactly like `console_log`/`network_log`.

- [ ] **Step 6: Verify with a real run through the web UI**

Run: `python qaclan.py serve --port 7823`

In the browser: create a Web script whose recorded actions hit any real endpoint that fires an XHR/fetch (e.g. record a visit to a page with an API call, or manually add a script that does `page.goto("https://httpbin.org/")` — httpbin's homepage fires no XHR, so prefer a page you know issues one, or reuse the local fixture from Task 3's verification by pointing a script at `http://127.0.0.1:8934/index.html` while that fixture server is running standalone: `python3 -m http.server 8934 --directory /tmp/qaclan_plan_verify_fixture` after copying the two fixture files there). Add the script to a suite, run it, then:

```bash
python3 -c "
from cli.db import get_conn
conn = get_conn()
row = conn.execute('SELECT captured_requests, captured_requests_count FROM script_runs ORDER BY started_at DESC LIMIT 1').fetchone()
print('count:', row['captured_requests_count'])
print('has data.json entry:', 'data.json' in (row['captured_requests'] or ''))
"
```

Expected: `count: 1` (or more) and `has data.json entry: True`.

- [ ] **Step 7: Commit**

```bash
git add web/routes/runs.py
git commit -m "feat(runs): persist and expose redacted captured requests per script run"
```

---

## Task 8: Frontend — "Captured Requests" section on the run-detail card

**Files:**
- Modify: `web/static/app.js` — inside `showRunResults()` (starts at line 4024; add the new block near the existing `diagnosticsBlock` around line 4113-4142, insert into the returned template around line 4195-4211), plus two new top-level functions

**Interfaces:**
- Consumes: `s.captured_requests` (JSON text, already redacted) / `s.captured_requests_count` from Task 7's response shape.
- Consumes: `showRequestReviewModal(requests, defaultCollectionName, startUrl)` from `web/static/api/views/request-review-modal.js:90` (existing, unchanged) — via dynamic `import()`, matching how `app.js` is loaded as a classic (non-module) script while the `api/` views are ES modules.

- [ ] **Step 1: Add the section-building block**

In `showRunResults()`, right after the existing `diagnosticsBlock` construction (ends at line 4142, right before the `// Error block.` comment at line 4144), insert:

```js
      // Captured Requests block (docs/superpowers/specs/2026-07-05-api-script-run-capture-design.md)
      let capturedRequestsBlock = ''
      const capturedRequests = s.captured_requests ? (() => { try { return JSON.parse(s.captured_requests) } catch { return [] } })() : []
      if (capturedRequests.length > 0) {
        const capId = 'cap-' + Math.random().toString(36).slice(2, 8)
        window._capturedReqState = window._capturedReqState || {}
        window._capturedReqState[capId] = {
          requests: capturedRequests,
          selected: new Set(capturedRequests.map((_, ri) => ri)),
        }
        const rowsHTML = capturedRequests.map((r, ri) => `
          <div class="cap-req-row">
            <input type="checkbox" class="cap-req-check" checked
                   onchange="toggleCapturedRequestSelect('${capId}', ${ri}, this.checked)">
            <span class="method-badge method-${escHtml(r.method)}">${escHtml(r.method)}</span>
            <span class="cap-req-url" title="${escHtml(r.url)}">${escHtml(r.url)}</span>
            <span class="cap-req-status">${r.response_status != null ? r.response_status : '—'}</span>
            <span class="cap-req-duration">${r.duration_ms != null ? r.duration_ms + 'ms' : '—'}</span>
          </div>`).join('')
        capturedRequestsBlock = `<div class="script-result-diagnostics">
          <div class="script-result-error-toggle" onclick="document.getElementById('${capId}').classList.toggle('collapsed')">
            <span class="script-result-error-label" style="color: var(--accent)">Captured Requests (${capturedRequests.length})</span>
            <span class="script-result-error-chevron">&#9662;</span>
          </div>
          <div id="${capId}" class="script-result-error-body collapsed">
            <div class="cap-req-list">${rowsHTML}</div>
            <div class="cap-req-actions">
              <button class="btn-ghost btn-sm" onclick="saveCapturedRequests('${capId}', ${JSON.stringify(s.name)})">Save Selected</button>
            </div>
          </div>
        </div>`
      }
```

Then add `${capturedRequestsBlock}` to the returned card template (lines 4195-4211), right after `${diagnosticsBlock}`:

```js
      return `
      <div class="script-result-card ${cls}">
        <div class="script-result-card-top">
          <div>
            <div class="script-result-name">${escHtml(s.name)}</div>
            <div class="script-result-meta">
              <span>Duration: ${s.duration_ms != null ? s.duration_ms + ' ms' : '—'}</span>
              ${(s.console_errors || 0) > 0 ? '<span class="meta-warn">Console errors/warnings: ' + (s.console_errors || 0) + '</span>' : '<span>Console errors/warnings: 0</span>'}
              ${(s.network_failures || 0) > 0 ? '<span class="meta-warn">Net failures: ' + (s.network_failures || 0) + '</span>' : '<span>Net: 0</span>'}
            </div>
          </div>
          ${badge}
        </div>
        ${errorBlock}
        ${diagnosticsBlock}
        ${capturedRequestsBlock}
      </div>`
    }).join('')}
    </div>`
```

- [ ] **Step 2: Add the two top-level handler functions**

Add these near `showRunResults` (e.g. directly above it, before line 4024):

```js
function toggleCapturedRequestSelect(capId, idx, checked) {
  const state = window._capturedReqState && window._capturedReqState[capId]
  if (!state) return
  if (checked) state.selected.add(idx)
  else state.selected.delete(idx)
}

async function saveCapturedRequests(capId, scriptName) {
  const state = window._capturedReqState && window._capturedReqState[capId]
  if (!state || !state.selected.size) { toast('Select at least one request', 'error'); return }
  const selected = state.requests.filter((_, i) => state.selected.has(i))
  const { showRequestReviewModal } = await import('./api/views/request-review-modal.js')
  closeModal()
  showRequestReviewModal(selected, scriptName, selected[0] ? selected[0].url : '')
}
```

- [ ] **Step 3: Syntax-check**

Run: `node --check web/static/app.js`
Expected: no output (exit code 0)

- [ ] **Step 4: Manual verification in the browser**

Run: `python qaclan.py serve --port 7823`

1. Run a suite/script whose action hits a real XHR/fetch endpoint (reuse the Task 7 verification setup).
2. Open the run's "Execution History" (via the runs page or the suite's "View last run").
3. Confirm a "Captured Requests (N)" toggle appears on the script's card, collapsed by default.
4. Click it — confirm rows show method badge, URL, status, duration, all checked by default.
5. Uncheck one row, click "Save Selected" — confirm the existing Discovery review modal opens with only the checked rows, collection name pre-filled, Flow/Library radio and "Organize into folders by endpoint" checkbox all present (unchanged, reused).
6. Pick "Save as Flow", save — confirm the request(s) land in the target collection.
7. Re-open Captured Requests, "Save Selected" again, pick "Save as Library" — confirm the grouping/comparison modal (`variant-comparison-modal.js`) opens as it does for every other Discovery path.

- [ ] **Step 5: Commit**

```bash
git add web/static/app.js
git commit -m "feat(run-detail): add Captured Requests section wired to the existing Discovery save flow"
```

---

## Task 9: CSS for the captured-request rows

**Files:**
- Modify: `web/static/style.css` — add near the existing `.diag-*`/`.script-result-diagnostics` block (`web/static/style.css:990-1025`)

**Interfaces:**
- Consumes existing classes: `.script-result-diagnostics`, `.script-result-error-toggle`, `.script-result-error-body`, `.method-badge`/`.method-<METHOD>` (`web/static/style.css:1520-1537`), `.btn-ghost`/`.btn-sm` (`web/static/style.css:449,463`) — all reused unchanged.

- [ ] **Step 1: Add the new rules**

Insert after the existing `.diag-entry`/`.diag-type` rules (after line 1025):

```css
.cap-req-list { display: flex; flex-direction: column; }
.cap-req-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border-subtle);
  font-size: 12px;
}
.cap-req-row:last-child { border-bottom: none; }
.cap-req-url {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: var(--font-mono, monospace);
  color: var(--text-secondary);
}
.cap-req-status,
.cap-req-duration {
  flex-shrink: 0;
  color: var(--text-muted);
  font-size: 11px;
  min-width: 36px;
  text-align: right;
}
.cap-req-actions {
  margin-top: 8px;
  display: flex;
  justify-content: flex-end;
}
```

- [ ] **Step 2: Manual verification**

Run: `python qaclan.py serve --port 7823`, repeat Task 8 Step 4's click-through in both light and dark theme (theme toggle in the UI). Confirm rows are legibly spaced, the URL truncates with ellipsis instead of wrapping/overflowing, and status/duration stay right-aligned in a fixed-width column.

- [ ] **Step 3: Commit**

```bash
git add web/static/style.css
git commit -m "style(run-detail): add captured-request row styling"
```

---

## Task 10: End-to-end regression pass

**Files:** none (verification only)

- [ ] **Step 1: Opt-in default-off walkthrough**

Run: `python qaclan.py serve --port 7823`

1. Run a suite **without** checking "Capture API Requests" (the checkbox's default state) — confirm the run-detail card shows no "Captured Requests" toggle at all, even though the script made XHR/fetch calls. Check the DB: `suite_runs.capture_requests` is `0`, `script_runs.captured_requests_count` is `0`/`NULL`.
2. Run the same suite from the ▶ Run Script solo quick-action — confirm no Captured Requests section appears there either (solo run always hardcodes capture off, Task 1.5 Step 2).
3. Re-run the suite **with** "Capture API Requests" checked — confirm the section now appears with the expected rows, and `suite_runs.capture_requests` is `1` in the DB.

- [ ] **Step 2: Full happy-path walkthrough (capture ON)**

1. Create/run a script that hits 2+ distinct endpoints, including at least one whose header or JSON field name matches the sensitive pattern (e.g. a request with an `Authorization` header) — confirm the Captured Requests list shows `{{AUTHORIZATION}}` in place of the raw value when a row is expanded/saved into the review modal (the review modal only shows header/param details on row-expand — verify via the modal's row detail view, not the collapsed list).
2. Confirm static-asset requests (any `<img>`/`<link rel=stylesheet>` the test page loads) never appear in the Captured Requests list.
3. Confirm the section is entirely absent (no empty toggle) for a script that made zero XHR/fetch calls, same as when capture is off — both cases collapse to the same "nothing to show" state.
4. Save via "Save as Flow" with "Organize into folders by endpoint" checked — confirm the saved request lands inside an auto-created folder (nested-folders feature, unmodified, already wired through `organize_into_folders`).
5. Re-run the same script twice into the same collection, this time save via "Save as Library" — confirm the variant-comparison modal correctly groups the two runs' identical-endpoint requests.

- [ ] **Step 3: Regression-check unrelated flows**

Confirm HAR import, OpenAPI import, and Record APIs mode (the three pre-existing Discovery paths) still work end to end — this plan added no code to `har_parser.py`'s existing call sites and no code to `discovery_service.py`, so this is a quick smoke check, not a deep regression pass. Also confirm an ordinary UI-only script (no API calls of interest, capture left off) runs and reports results exactly as before this plan — no new columns/UI visible, no behavior change for the default path.

- [ ] **Step 4: Clean up verification artifacts**

```bash
rm -rf /tmp/qaclan_plan_verify
```

No commit for this task — it's verification only.
