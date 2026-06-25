# API Test Reports — Design Spec
Date: 2026-06-23

## Problem

API collection runs (`RunnerService.run_collection`) and single-request sends (`run_request`) return results in-memory only. Nothing is persisted. No downloadable report exists. Users have no run history for API tests.

## Scope

- Auto-persist **collection runs** to DB (every `/api/collections/<id>/run` call)
- Single-request sends (`/api/api-requests/<id>/send`) stay ephemeral — consistent with how individual script sends work
- Runs page gets a second tab: **API Runs** alongside existing **Regression Runs**
- Downloadable self-contained HTML report per collection run

## Out of Scope

- Individual request run history
- Cloud sync of API run results
- PDF export (HTML-only, opens in browser, prints to PDF natively)

---

## Data Layer

### Migration (cli/db.py)

New migration function added to `_run_migrations()`:

```sql
CREATE TABLE IF NOT EXISTS api_collection_runs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL,
    collection_id TEXT NOT NULL REFERENCES api_collections(id) ON DELETE CASCADE,
    collection_name TEXT NOT NULL,
    env_name      TEXT,
    status        TEXT NOT NULL,   -- PASSED | FAILED | ERROR | RUNNING
    total         INTEGER NOT NULL DEFAULT 0,
    passed        INTEGER NOT NULL DEFAULT 0,
    failed        INTEGER NOT NULL DEFAULT 0,
    error_count   INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT NOT NULL,
    finished_at   TEXT
);

CREATE TABLE IF NOT EXISTS api_request_results (
    id                  TEXT PRIMARY KEY,
    collection_run_id   TEXT NOT NULL REFERENCES api_collection_runs(id) ON DELETE CASCADE,
    api_request_id      TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
    request_name        TEXT NOT NULL,
    method              TEXT,
    url                 TEXT,
    order_index         INTEGER NOT NULL DEFAULT 0,
    status              TEXT,              -- PASSED | FAILED | ERROR
    status_code         INTEGER,
    response_body       TEXT,
    response_headers    TEXT,              -- JSON string
    duration_ms         INTEGER,
    assertion_results   TEXT,              -- JSON string
    error_message       TEXT,
    started_at          TEXT,
    finished_at         TEXT
);
```

`collection_name`, `request_name`, and `url` are snapshots taken at run time. Renaming a request or collection after the fact does not alter history.

---

## Backend

### New file: web/api/repositories/collection_run_repo.py

```
CollectionRunRepo
  create_run(collection_id, project_id, collection_name, env_name, started_at) -> str (run_id)
  finish_run(run_id, status, total, passed, failed, error_count, finished_at)
  create_request_result(collection_run_id, req, result, order_index)
  list_runs(project_id) -> list[dict]          # for the Runs page table
  get_run(run_id, project_id) -> dict | None   # summary + request_results list
```

### Modified: web/api/services/runner_service.py — run_collection()

1. Insert `api_collection_runs` row (status=`RUNNING`, `started_at=now`)
2. For each request: run it, then immediately insert `api_request_results` row
3. After all requests: `UPDATE api_collection_runs SET status=..., finished_at=..., total/passed/failed/error_count`
4. Return dict includes `run_id` so the frontend can navigate to it

### New file: web/api/routes/api_collection_runs.py

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/api-collection-runs` | List runs for active project |
| GET | `/api/api-collection-runs/<run_id>` | Run detail + all request results |
| GET | `/api/api-collection-runs/<run_id>/report` | HTML report (`?view=1` inline, default attachment) |

Blueprint registered in the Flask app alongside existing API blueprints.

### New file: cli/api_report.py

Mirrors `cli/report.py`. `generate_api_html_report(run_id) -> str` reads from DB and renders self-contained HTML. No external dependencies — all CSS/JS inlined.

---

## Report Format (HTML)

Single self-contained HTML file. No internet required. Opens in any browser.

### Header
- Collection name (large)
- Run date/time · Environment used (or "No environment")
- Status badge: green PASSED / red FAILED
- 4 stat cards: **Total** · **Passed** · **Failed** · **Duration**
- Pass rate % bar

### Request Table

Columns: `#` · Method badge · Request name · Resolved URL · Status badge · HTTP code · Duration (ms) · Assertions (N/N passed)

- Method badges are color-coded: GET=blue, POST=green, PUT=orange, DELETE=red, PATCH=yellow
- Status badge: green PASSED / red FAILED / gray ERROR
- Each row is **clickable to expand** detail panel

### Expanded Detail Panel (per request)

- **Request** section: resolved headers sent, query params, body (if any)
- **Response** section: headers as table, body (syntax-highlighted JSON if parseable, raw monospace otherwise)
- **Assertions** section: each assertion as a row — type, expected, actual, pass/fail icon with plain-language label ("Status code equals 200 ✓")

### Footer
- "Generated by QAClan · <timestamp> · v<version>"

### Tone
- Non-tech: color, badges, plain-language assertion labels ("Response body contains 'success' ✓")
- Tech: exact values, raw JSON, full URLs, HTTP codes, ms timings

---

## Frontend — Runs Page

### Tab switcher

`renderRunsPage()` in `web/static/app.js` gains a tab bar at the top:

```
[ Regression Runs ]  [ API Runs ]
```

Default tab: Regression Runs (preserves existing behavior). Tab state stored in a local variable, not URL.

### API Runs tab content

Same table style as Regression Runs:

| Run ID | Collection | Status | Results | Started | Actions |
|--------|------------|--------|---------|---------|---------|
| mono ID | collection name | PASSED/FAILED badge | N/M passed | date | View · Report |

- **View** button → modal showing per-request table (method, name, URL, code, duration, assertions)
- **Report** button → opens HTML in new tab (`?view=1`) + triggers download attachment (same pattern as existing `downloadReport()`)

### After collection run completes

`run_collection` route now returns `run_id` in the response. The frontend (collections view) uses this to optionally show a "View Report" link in the run-results panel after execution.

---

## File Checklist

| File | Change |
|------|--------|
| `cli/db.py` | New migration: `api_collection_runs` + `api_request_results` tables |
| `cli/api_report.py` | New: HTML report generator |
| `web/api/repositories/collection_run_repo.py` | New: DB access for both new tables |
| `web/api/services/runner_service.py` | Modify `run_collection` to persist runs |
| `web/api/routes/api_collection_runs.py` | New: 3 routes (list, get, report) |
| `web/api/__init__.py` or app init | Register new blueprint |
| `web/static/app.js` | Add tab switcher + API Runs tab to `renderRunsPage` |

---

## Key Invariants

- Collection run delete cascades to `api_request_results` automatically (FK + ON DELETE CASCADE)
- `api_collection_runs.collection_id` FK uses ON DELETE CASCADE — deleting a collection wipes its run history
- Single-request sends remain ephemeral — no schema or route changes needed there
- Existing `api_runs` table (linked to `suite_runs`) is untouched
- Report generation is synchronous and on-demand (no file storage, generated fresh per request) — same as `cli/report.py`
