# 25 - Coverage View

Deep-dive on feature #25 from [feature-ideas.md](../feature-ideas.md). Covers what "E2E URL coverage" means (it is not code coverage), how to collect it, and what the view should show.

---

## What this is NOT

Code coverage (Istanbul, nyc, coverage.py) measures which JavaScript or Python lines were executed. That is a unit/integration testing concern.

This feature is **URL/route coverage**: which pages, API endpoints, and user flows did your E2E tests actually exercise? The answer reveals where your tests have blind spots at the user-facing level.

## The problem

A QAClan project with 30 scripts appears comprehensive. But nobody knows:

- Is `/admin/billing` tested?
- Does any test touch the `/settings/security` page?
- Are the error pages (`/404`, `/500`) ever visited?
- Which API endpoints does the test suite call?

Without a coverage view, teams build tests by intuition. With it, they prioritize by data.

## Example

```
Coverage report — my-app — smoke suite
────────────────────────────────────────────
Pages visited:
  ✅  /login            tested by 4 scripts
  ✅  /dashboard        tested by 6 scripts
  ✅  /cart             tested by 3 scripts
  ⚠️  /settings/profile  tested by 1 script (partial)
  ❌  /settings/security  never tested
  ❌  /admin/billing     never tested
  ❌  /admin/users       never tested

API endpoints hit:
  ✅  POST /api/auth/login      (4 scripts)
  ✅  GET  /api/cart            (3 scripts)
  ⚠️  POST /api/payment         (1 script)
  ❌  DELETE /api/users/:id     never tested
  ❌  GET  /api/admin/reports   never tested

Coverage: 11 of 20 known URLs = 55%
```

## Impact

| Dimension | Effect |
|---|---|
| Test prioritization | Reveals untested areas instantly. Team writes tests for /admin/billing next, not the 5th variation of /login. |
| Audit / compliance | "We test 100% of critical user paths." Now provable with data instead of claims. |
| Regression risk map | Untested pages = high regression risk. Coverage view is a risk map. |
| Onboarding value | New QA engineer joins, opens coverage view, immediately knows where to focus. |

Overall: **medium impact** for small projects, **high impact** for large projects with many routes. Differentiated feature — most E2E tools don't offer route coverage (only code coverage).

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **Istanbul / nyc** | JavaScript code line coverage. | Lines, not user-visible routes. Different concept entirely. |
| **Postman Coverage** | API endpoint coverage from your Postman collection. | HTTP API only. No page/route coverage. Not E2E. |
| **Playwright Coverage** | `page.coverage.startJSCoverage()` — JS code coverage inside Playwright. | Code lines inside the browser. Not routes or pages. |
| **sitemap.xml audit** | Compare sitemap against visited URLs. | External tool. Manual. No integration. |

**Our diff:** Route coverage tied directly to QAClan run history. No extra tools. Coverage view shows trends over time (coverage improving or declining). Covers both page navigations and API calls.

## Data collection

### What to capture per script run

During execution, the harness intercepts:

**1. Page navigations** — `page.goto()` calls and URL changes after user actions:
```python
# In harness: capture every page.goto() call
# Also listen to page.on("framenavigated") for redirect chains
current_urls = []
page.on("framenavigated", lambda frame: current_urls.append(frame.url) if frame == page.main_frame else None)
```

**2. Network requests** — already partially captured in `network_log`:
```python
# Intercept requests
page.on("request", lambda req: record_request(req.method, req.url))
```

Strip query params and replace dynamic segments for grouping:
- `/api/users/123/orders/456` → `/api/users/:id/orders/:id`
- `/products/blue-widget` → `/products/:slug`

The normalization prevents infinite unique routes from dynamic IDs.

### Storage

```sql
CREATE TABLE run_coverage (
    id             TEXT PRIMARY KEY,
    script_run_id  TEXT NOT NULL REFERENCES script_runs(id) ON DELETE CASCADE,
    url_type       TEXT NOT NULL,  -- 'page' | 'api'
    method         TEXT,           -- NULL for pages, GET/POST/etc for API
    url_pattern    TEXT NOT NULL,  -- normalized: /api/users/:id
    raw_url        TEXT NOT NULL,  -- original: /api/users/123
    created_at     TEXT NOT NULL
);
```

Aggregate at query time for the coverage view — don't pre-compute percentages. They change as more scripts run.

## Known URLs source

To compute coverage percentage, we need to know what exists. Three sources:

| Source | How | Accuracy |
|---|---|---|
| **Sitemap.xml** | Fetch from base URL + parse. | Page URLs only. May be incomplete. |
| **Route file** | Parse app's router file (Next.js pages/, Express router, Django urls.py). | High accuracy but app-specific. Complex to parse. |
| **Discovered from runs** | Any URL ever visited by any test is known. Coverage = visited / total discovered. | Self-referential but always accurate. Grows over time. |
| **Manual entry** | User enters known URLs in QAClan settings. | Tedious but under user control. |

**v1 approach: discovered URLs only.** Every URL visited by any test ever = the known set. Coverage = (distinct URLs in last run) / (distinct URLs ever seen). Simple, no config, grows organically.

v2: sitemap.xml import + manual entries. v3: route file parsing.

## Coverage view UI

**Coverage dashboard** (suite-level):
- Donut chart: tested / untested / partial (visited by <2 scripts).
- Two panels: Pages and API endpoints.
- Each URL row: pattern, # scripts that tested it, last tested date, badges (new, missing, partial).
- Sort by: untested first, alphabetical, most tested.
- Filter by: pages only, API only, never tested, partial.

**Coverage trend chart:**
- Line graph: coverage % over last 30 days.
- Shows if the suite is growing or regressing in coverage.

**Per-script coverage contribution:**
- On script detail page: "URLs this script covers" list.
- Helps when deciding which scripts to add to the smoke suite.

## Implementation path

### Phase 1 — data collection

- Add `run_coverage` table migration in [cli/db.py](../../cli/db.py).
- Python harness: capture `goto()` calls and network requests. Write to a temp file during run. Runner reads and inserts into DB after run completes.
- Add URL normalization function: strip dynamic segments (numeric IDs, UUIDs, slugs).

### Phase 2 — coverage view UI

- Flask route: `GET /api/coverage?suite_id=&run_id=` — returns aggregated coverage data.
- Coverage tab on project dashboard.
- Page + API panels with tested/untested badges.

### Phase 3 — known URL sources

- Sitemap.xml fetch + parse: `GET /api/coverage/sitemap?url=<base_url>` triggers fetch.
- Manual URL entry UI: user adds known routes that tests should cover.
- Coverage % = (visited known URLs) / (total known URLs).

### Phase 4 — trend chart

- Aggregate coverage % per suite run over time.
- Coverage trend line chart on the dashboard.

## URL normalization rules

```python
import re

def normalize_url(url):
    # Remove query string and fragment
    url = url.split("?")[0].split("#")[0]
    # Replace numeric IDs
    url = re.sub(r"/\d+", "/:id", url)
    # Replace UUIDs
    url = re.sub(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", "/:uuid", url)
    # Replace slugs (all-lowercase with hyphens, not a keyword)
    url = re.sub(r"/[a-z][a-z0-9-]{2,}/", "/:slug/", url)
    return url.rstrip("/") or "/"
```

Normalization is lossy — `/api/users/:id` covers both `/api/users/123` and `/api/users/456`. Good for the coverage view; do not use normalized form as the canonical identifier anywhere else.

## Open questions

- **Cross-origin requests.** Tests on `app.example.com` may call `api.example.com`. Should the coverage view separate them? Yes — show domain as a filter/group dimension.
- **Static assets.** Tests will fetch CSS, JS, images. These are noise in the coverage view. Filter out: `*.js`, `*.css`, `*.png`, `*.woff`, `/_next/*`, `/static/*`. Add to a default exclusion list, user-configurable.
- **Coverage for non-browser tests.** Some scripts test via API directly (no browser). Include their HTTP calls in the API coverage panel, but exclude them from the page coverage panel.

## Next concrete step

Add `run_coverage` table migration. Update Python harness to capture `goto()` URLs and network requests to a temp file. Add runner code to parse the temp file and insert coverage rows after run completes. Validate that the raw data is collected correctly before building any UI.
