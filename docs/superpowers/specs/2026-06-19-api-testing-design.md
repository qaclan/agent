# API Testing — Design Spec
Date: 2026-06-19

## Problem

Postman is the dominant API testing tool but has widely-reported pain points:

1. **Mandatory cloud account** — v10+ requires login; collections sync to Postman's servers with no opt-out
2. **Broken git collaboration** — collections are JSON blobs; merging = JSON conflict hell
3. **Runner disconnected from workflow** — Collection Runner is a separate modal; results live inside Postman, not in CI artifact stores; Newman (the CLI) is a separate tool
4. **Shallow secret management** — environments are flat key-value, not encrypted; shared by exporting plaintext JSON
5. **JS-only test scripts** — locked to `pm.test()` / `pm.expect()` sandbox; no async/await (pre-v10), no `require()`
6. **No E2E bridge** — API tests and browser automation tests live in separate universes; no unified report, no state sharing

QAClan already owns the browser automation execution context (Playwright runner, suite runner, state.json, step_runs). This spec adds API testing as a first-class entity that integrates into the same suite, report, and state bridge.

## Differentiated Position

No tool today combines API testing + browser automation into one local-first suite with a unified report. QAClan's killer feature: **an API call as a step inside an E2E flow** — set up state via API, verify via browser, clean up via API, one report.

## Decisions

| Question | Decision |
|---|---|
| Standalone vs bridge | Both — same data model serves independent API testing and mixed suites |
| Data model approach | First-class `api_requests` table (not file-based, not script wrapper) |
| Complexity level | Full — auth presets, pre/post scripts, chained flows, assertions |
| Primary differentiator | Unified report across API runs and Playwright runs |
| UI style | QAClan-native (single scrollable page, not Postman tab clone) |
| Script sandbox | Both JS and Python (matches existing multi-language support) |

---

## Section 1: Data Model

### New table: `api_requests`

```sql
CREATE TABLE api_requests (
    id              TEXT PRIMARY KEY,          -- "apireq_xxxxxxxx"
    project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    feature_id      TEXT REFERENCES features(id) ON DELETE SET NULL,
    collection_id   TEXT REFERENCES api_collections(id) ON DELETE SET NULL,
    name            TEXT NOT NULL,
    method          TEXT NOT NULL DEFAULT 'GET',
    url             TEXT NOT NULL,
    headers         TEXT NOT NULL DEFAULT '[]',   -- JSON [{key, value, enabled}]
    params          TEXT NOT NULL DEFAULT '[]',   -- JSON [{key, value, enabled}]
    body_type       TEXT DEFAULT NULL,            -- none | raw | form | multipart | graphql
    body            TEXT DEFAULT NULL,
    auth_type       TEXT NOT NULL DEFAULT 'none', -- none | bearer | basic | api_key | oauth2
    auth_config     TEXT NOT NULL DEFAULT '{}',   -- JSON per auth_type
    pre_script      TEXT DEFAULT NULL,
    pre_lang        TEXT DEFAULT 'js',            -- js | python
    post_script     TEXT DEFAULT NULL,
    post_lang       TEXT DEFAULT 'js',
    assertions      TEXT NOT NULL DEFAULT '[]',   -- JSON assertion array
    follow_redirects INTEGER DEFAULT 1,
    timeout_ms      INTEGER DEFAULT 30000,
    created_at      TEXT NOT NULL
);
```

All JSON columns are TEXT (SQLite has no JSONB). Use `json_extract()` for server-side querying if needed.

### Column explanations

- **pre_script / pre_lang** — code that runs before the HTTP call. Use cases: generate dynamic headers (HMAC, timestamp nonce), read state.json and modify the request conditionally.
- **post_script / post_lang** — code that runs after the response. Primary use case: extract values from response (`qc.set("token", response.json()["token"])`) and write to state.json so downstream suite items receive them.
- **follow_redirects** — whether the HTTP client follows 3xx redirects automatically. Set to `false` to assert on the redirect itself (Location header, status code) rather than the final destination.
- **assertions** — structured pass/fail checks that determine request status (PASSED | FAILED). Without assertions a request has no test outcome, just a completion.

### Assertions JSON shape

```json
[
  {"type": "status",       "op": "eq",       "value": 200},
  {"type": "json_path",    "path": "$.id",   "op": "exists"},
  {"type": "json_path",    "path": "$.name", "op": "eq",      "value": "Alice"},
  {"type": "header",       "key": "Content-Type", "op": "contains", "value": "application/json"},
  {"type": "response_time","op": "lt",       "value": 500},
  {"type": "body_text",    "op": "contains", "value": "success"}
]
```

Operators: `eq`, `ne`, `lt`, `gt`, `contains`, `exists`, `not_exists`, `matches` (regex).

### New table: `api_collections`

Grouping layer for requests. One level only — no nested folders.

```sql
CREATE TABLE api_collections (
    id          TEXT PRIMARY KEY,   -- "apicol_xxxxxxxx"
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    created_at  TEXT NOT NULL
);
```

### Modified: `suite_items`

Migration adds `item_type` and `api_request_id` via `ALTER TABLE` (SQLite supports both). `script_id` must remain NOT NULL in the column definition — SQLite cannot change nullability via `ALTER TABLE`. Enforcement of "exactly one non-NULL" moves to the application layer (runner + API routes validate before insert).

```sql
ALTER TABLE suite_items ADD COLUMN item_type TEXT NOT NULL DEFAULT 'script';
-- values: 'script' | 'api_request'
ALTER TABLE suite_items ADD COLUMN api_request_id TEXT REFERENCES api_requests(id) ON DELETE CASCADE;
```

`script_id` stays as-is in the schema. For `api_request` rows, `script_id` holds a sentinel value or the migration pre-populates it with a placeholder — application layer ignores it when `item_type = 'api_request'`.

> **Migration order:** `api_collections` table must be created before `api_requests` (foreign key dependency). Both before `suite_items` migration.

### New table: `api_runs`

Parallel to `script_runs`. Same shape so reporting works uniformly.

```sql
CREATE TABLE api_runs (
    id                  TEXT PRIMARY KEY,
    suite_run_id        TEXT NOT NULL REFERENCES suite_runs(id) ON DELETE CASCADE,
    api_request_id      TEXT NOT NULL REFERENCES api_requests(id) ON DELETE CASCADE,
    order_index         INTEGER NOT NULL DEFAULT 0,
    status              TEXT,             -- PASSED | FAILED | ERROR
    status_code         INTEGER,
    response_body       TEXT,
    response_headers    TEXT,             -- JSON
    duration_ms         INTEGER,
    assertion_results   TEXT,             -- JSON [{type, path, op, value, passed, actual}]
    error_message       TEXT,
    started_at          TEXT,
    finished_at         TEXT
);
```

### State bridge: `state.json`

`state.json` already bridges cookies/localStorage between Playwright scripts in a suite run. Extended — post-response scripts write extracted values via `qc.set()`. Next suite item (API or Playwright) reads them as env vars: `QACLAN_STATE_<key>`.

Example flow:
```
Step 1: POST /users  →  post_script: qc.set("user_id", response.json().id)
Step 2: Playwright script  →  reads os.environ["QACLAN_STATE_user_id"]
Step 3: DELETE /users/{{user_id}}  →  {{user_id}} resolved from state.json
```

---

## Section 2: API Runner

### New file: `cli/api_runner.py`

Executes one `api_request` row. Runs in-process via `httpx` (Python). No subprocess needed for the HTTP call itself — subprocesses only for pre/post scripts.

### Execution flow

```
1. Load api_request row from DB
2. Resolve {{var}} in url, headers, body, params
   — reads active environment (env_vars table) + state.json
   — falls back to empty string + logs warning
3. Apply auth_config → inject into headers/params per auth_type
4. Run pre_script in sandbox (subprocess, if set)
5. Send HTTP request via httpx
6. Run post_script in sandbox (subprocess, if set)
7. Evaluate assertions → [{passed, actual}]
8. Write api_runs row
9. Return PASSED | FAILED | ERROR
```

### Variable resolution

`{{var}}` syntax (Postman-compatible). Resolution order:
1. Active environment vars (`env_vars` table for active `environment_id`)
2. `state.json` values from prior suite items
3. Empty string + warning logged

### Auth injection

| `auth_type` | Behavior |
|---|---|
| `none` | No-op |
| `bearer` | `Authorization: Bearer <token>` header |
| `basic` | `Authorization: Basic base64(user:pass)` |
| `api_key` | Key injected into header or query param (per `auth_config.in`) |
| `oauth2` | Fetches token via `client_credentials` grant from `token_url`, cached per suite_run |

`auth_config` values support `{{var}}` resolution. Example for bearer:
```json
{"token": "{{auth_token}}"}
```

### Script sandbox

**Python** — subprocess via runtime venv. `qc` helper object injected:
```python
# pre_script
qc.set_header("X-Timestamp", str(int(time.time())))
qc.set_param("nonce", generate_nonce())

# post_script
qc.set("user_id", response.json()["id"])
qc.set("token", response.headers["X-Auth-Token"])
```

**JS** — subprocess via `node` in runtime. Same `qc` API:
```js
// pre_script
qc.setHeader("X-Timestamp", Date.now().toString())

// post_script
qc.set("user_id", response.json().id)
qc.set("token", response.headers["x-auth-token"])
```

Sandbox constraints: read access to current state.json, write via `qc.set()`. No outbound network. No filesystem.

### Suite runner integration

`web/routes/runs.py` — item dispatch by type:

```python
for item in suite_items:
    if item["item_type"] == "script":
        run_playwright_script(item, ...)    # existing path, unchanged
    elif item["item_type"] == "api_request":
        run_api_request(item, ...)          # new path, in-process
```

Sequential ordering preserved. Future parallel mode (feature #7) treats api_requests as faster items in the worker pool — no special casing needed.

---

## Section 3: UI

### New nav section: "API"

Added to sidebar alongside Scripts and Suites.

Sub-views:
- **Collections** — requests grouped by `api_collections`
- **Requests** — flat list of all project requests
- **+ Discover** — entry point for all three discovery paths

### Request editor

Single scrollable page. Sections collapse/expand. No nested tabs (not a Postman clone).

```
[GET ▾]  https://{{base_url}}/api/users/{{user_id}}      [Send]
─────────────────────────────────────────────────────────
▾ Params          key-value table, enabled toggle per row
▾ Headers         key-value table, enabled toggle per row
▾ Body            [none | raw | form | multipart | graphql]
▾ Auth            [none | Bearer | Basic | API Key | OAuth2]
▾ Pre-script      [JS ▾ | Python]  +  code editor
▾ Assertions      point-and-click builder
▾ Post-script     [JS ▾ | Python]  +  code editor
─────────────────────────────────────────────────────────
Response (after Send)
Status: 201  Time: 142ms  Size: 1.2kb
[Body] [Headers] [Assertion Results]
{ "id": 42, "name": "Alice" }
```

### Assertion builder

No-code rows. Each row:
```
[status code ▾]  [equals ▾]      [200]         [×]
[json path   ▾]  [exists  ▾]     [$.data.id]   [×]
[response time▾] [less than ▾]   [500]         [×]
[+ Add assertion]
```

After Send, inline pass/fail per row:
```
✓ status code equals 200
✗ json path $.data.token exists  →  actual: null
✓ response time < 500ms  →  actual: 142ms
```

### Collections sidebar

```
API
├── Collections
│   ├── Auth Flows
│   │   ├── POST /login
│   │   └── POST /refresh
│   └── User Management
│       ├── GET /users
│       ├── POST /users
│       └── DELETE /users/:id
├── Requests (ungrouped)
└── [+ Discover]
```

One level of nesting only. No folder-within-folder (avoids Postman hierarchy hell).

### Suite builder

"Add API Request" button alongside existing "Add Script":

```
Suite: Checkout Flow
├── [API]  POST /users            creates test user
├── [E2E]  login-flow.py          logs in as test user
├── [E2E]  checkout.py            completes purchase
└── [API]  DELETE /users/:id      cleanup
[+ Add Script]  [+ Add API Request]
```

### Run report (unified timeline)

`api_runs` and `script_runs` interleaved by `order_index`:

```
Suite Run: Checkout Flow  ●  FAILED  ●  3m 12s
├── ✓ [API]  POST /users          142ms
├── ✓ [E2E]  login-flow.py        48s
├── ✗ [E2E]  checkout.py          2m 10s
└── ✓ [API]  DELETE /users/:id    89ms
```

Clicking an API row expands inline: status code, assertion results, response body preview, duration. No separate page for simple requests.

---

## Section 4: CLI Commands

New command group `qaclan api`:

```bash
# List all API requests in active project
qaclan api list

# Run single request by name or ID
qaclan api run "POST /users"
qaclan api run apireq_3f9a1b2c

# Run all requests in a collection
qaclan api run --collection "Auth Flows"

# Export to Bruno-compatible .bru files
qaclan api export --collection "Auth Flows" --output ./api/

# Import from Postman collection JSON
qaclan api import postman_collection.json

# Import from Bruno .bru files
qaclan api import ./api/ --format bruno

# Import from HAR file
qaclan api import session.har --format har

# Import from OpenAPI spec (file or URL)
qaclan api import openapi.json --format openapi
qaclan api import https://api.example.com/openapi.json --format openapi
```

### Postman import mapper

`pm.test()` / `pm.expect()` post-scripts stored as-is in `post_script` (JS). `pm.environment.set()` mapped to `qc.set()` via a thin shim injected at runtime. Folders → `api_collections`. Variables → `env_vars`.

### HAR recording flag

```bash
qaclan suite run smoke --record-har=session.har
```

Injects `context.recordHar({path: "session.har"})` into Playwright harness. HAR importable afterward via `qaclan api import`.

---

## Section 5: API Discovery

Three paths to populate requests without manual entry.

### Path 1 — Capture from Playwright run

All script harnesses (Python, JS, TS) gain a capture hook. During any run, all outgoing XHR/fetch calls are recorded to `captured_requests.json` in the run directory.

```json
[
  {
    "method": "POST",
    "url": "https://staging.app.com/api/auth/login",
    "request_headers": {"Content-Type": "application/json"},
    "request_body": "{\"email\":\"test@x.com\",\"password\":\"secret\"}",
    "status_code": 200,
    "response_headers": {"Content-Type": "application/json"},
    "response_body": "{\"token\":\"eyJ...\"}",
    "duration_ms": 142
  }
]
```

**Python harness:** `page.on("request", ...)` + `page.on("response", ...)` listeners.
**JS/TS harness:** same via Playwright event listeners.

UI shows "Captured Requests" tab on run detail page. "Save as API Request" button pre-fills editor. Sensitive values auto-detected by key name (`password`, `token`, `secret`, `authorization`) and replaced with `{{var_name}}` placeholders.

"From last run capture" in Discover modal lists 10 most recent script runs with captured requests.

### Path 2 — HAR import

UI: drag-and-drop HAR file → parse all requests → checkbox selection → "Import Selected" → creates `api_requests` rows. Same auto-suggest logic for assertions and `{{var}}` replacement as Path 1.

Playwright HAR recording enabled via `--record-har` flag (see CLI section).

### Path 3 — OpenAPI / Swagger import

File upload or URL. Supports OpenAPI 3.x and Swagger 2.x.

Per endpoint generates:
- `api_requests` row: method, URL with `{{path_params}}`, sample body from schema `example` field
- Assertions from response schema: expected status codes, required JSON fields present
- Grouped into `api_collections` by OpenAPI tag

### Discovery UI entry point

```
[+ Discover]
  ├── From Playwright run capture
  ├── Import HAR file
  └── Import OpenAPI / Swagger
```

---

## Out of Scope (This Version)

- Mock server / response recording
- WebSocket testing
- GraphQL schema explorer (body type `graphql` supported but no schema introspection UI)
- Load / performance testing
- Proxy mode (HAR import covers the same use case with less complexity)
- Cloud sync for API requests (local-first only at launch)
- Run approval gates / GitHub Checks integration

---

## Open Questions

None — all decisions made above.
