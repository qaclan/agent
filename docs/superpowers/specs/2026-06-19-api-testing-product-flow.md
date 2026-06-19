# API Testing — Product & UX Flow
**Audience:** Product owners, stakeholders, designers
**Date:** 2026-06-19

This document covers what users see and do at every step of the API testing feature. No backend details — only user journeys, screen flows, and UI behaviour.

---

## What We Are Building (Plain English)

QAClan today helps teams record and run browser tests (clicking buttons, filling forms, checking pages). This feature adds **API testing** — sending HTTP requests to a backend and checking if the responses are correct.

The key difference from every other API tool: **API tests and browser tests live in the same place, run together, and produce one shared report.** No more switching between Postman for API and Playwright for browser.

---

## Concepts (For Product Owners)

| Term | What it means |
|---|---|
| **API Request** | A single HTTP call — e.g. "Create a user" or "Get order details" |
| **Collection** | A named group of related requests — e.g. "Auth Flows", "Checkout API" |
| **Assertion** | A check on the response — e.g. "status must be 200", "response must contain an ID" |
| **Suite** | An ordered list of steps (mix of API requests and browser tests) that run together |
| **State Bridge** | When a value from an API response (e.g. a user ID) is automatically passed into the next step |
| **Discovery** | Ways to find and import existing APIs without typing them by hand |

---

## Overview: Feature Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        QAClan — API Section                     │
│                                                                 │
│   ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐  │
│   │  Collections  │   │   Requests   │   │   + Discover     │  │
│   │  (grouped)    │   │  (all, flat) │   │  (import / find) │  │
│   └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘  │
│          │                  │                     │            │
│          ▼                  ▼                     ▼            │
│   Browse & run         Open & edit         Import from:        │
│   collections          any request         • Playwright run    │
│                                            • HAR file          │
│                                            • OpenAPI spec      │
│                                            • Postman export    │
│                                            • Bruno files       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
              Requests added to Suites (mixed with browser tests)
                              │
                              ▼
                   One unified run report
```

---

## User Flow 1: Creating a Request Manually

**Entry point:** User clicks "API" in the sidebar → clicks "+ New Request"

```
Sidebar                    Request Editor
──────────                 ─────────────────────────────────────────────
API
├── Collections            ┌─────────────────────────────────────────┐
├── Requests       ──────► │ [POST ▾]  https://api.myapp.com/users   │
└── + Discover             │                                  [Send]  │
                           ├─────────────────────────────────────────┤
                           │ ▾ Params        (key-value rows)        │
                           │ ▾ Headers       (key-value rows)        │
                           │ ▾ Body          [raw JSON ▾]            │
                           │   { "name": "Alice", "role": "admin" }  │
                           │ ▾ Auth          [Bearer Token ▾]        │
                           │   Token: {{auth_token}}                 │
                           │ ▾ Pre-script    (optional code)         │
                           │ ▾ Assertions    (point-and-click)       │
                           │ ▾ Post-script   (optional code)         │
                           └─────────────────────────────────────────┘
```

**Step-by-step:**

1. User picks method from dropdown (GET / POST / PUT / PATCH / DELETE / HEAD)
2. Types or pastes the URL — can use `{{variables}}` like `{{base_url}}/users`
3. Adds headers and params as key-value rows. Each row has an enable/disable toggle — disabled rows are saved but not sent
4. Picks body type and writes body content (JSON, form data, etc.)
5. Picks auth type — QAClan injects the auth header automatically so it does not appear in the headers table
6. Adds assertions (see Flow 3 below)
7. Clicks **Send** → sees response inline (see Flow 4)
8. Clicks **Save** → request appears in the Requests list

**Variable syntax:** `{{variable_name}}` anywhere in the URL, headers, or body. QAClan fills in the value from the active environment. Highlighted in the editor so users can see which values are dynamic.

---

## User Flow 2: Discovery — Finding APIs Without Typing

### 2A — From a Playwright Run (Zero Extra Work)

Every time a browser test runs, QAClan silently records all the API calls the browser made in the background.

```
User runs any browser test
         │
         ▼
Test completes (pass or fail)
         │
         ▼
Run detail page appears
         │
         ├── [Steps]  [Screenshots]  [Captured Requests ●3]  ← new tab
         │
         ▼
User clicks "Captured Requests"

┌──────────────────────────────────────────────────────┐
│ Captured from: login-flow.py  (run 2 minutes ago)    │
├──────────────────────────────────────────────────────┤
│ ☑  POST  /api/auth/login          200   142ms        │
│ ☑  GET   /api/users/me            200    89ms        │
│ ☐  GET   /static/icons/logo.svg   200     3ms        │  ← static asset, skip
├──────────────────────────────────────────────────────┤
│                          [Save Selected as Requests] │
└──────────────────────────────────────────────────────┘
```

User checks what they want → clicks Save → requests appear in the API section, pre-filled with method, URL, headers, body. Sensitive values (passwords, tokens) are automatically replaced with `{{variable}}` placeholders.

---

### 2B — Import a HAR File

HAR = a file browsers can export from DevTools that contains a recording of all network traffic.

```
User opens Chrome DevTools → Network tab
User does actions on the app (login, checkout, etc.)
User clicks "Export HAR" in DevTools
         │
         ▼
In QAClan: API → + Discover → Import HAR file
         │
         ▼
┌──────────────────────────────────────────────────────┐
│ Drop HAR file here or [Browse]                       │
└──────────────────────────────────────────────────────┘
         │
         ▼ (after upload)
┌──────────────────────────────────────────────────────┐
│ Found 47 requests in session.har                     │
│ Showing API calls only (static assets hidden)        │
├──────────────────────────────────────────────────────┤
│ ☑  POST  /api/auth/login                            │
│ ☑  GET   /api/dashboard/stats                       │
│ ☑  POST  /api/orders                                │
│ ☐  GET   /api/feature-flags   (looks like internal) │
├──────────────────────────────────────────────────────┤
│ Add to collection: [Auth Flows ▾]   [Import 3]      │
└──────────────────────────────────────────────────────┘
```

---

### 2C — Import from OpenAPI / Swagger Spec

If the backend has API documentation (OpenAPI or Swagger), QAClan can read it and generate all request stubs automatically.

```
API → + Discover → Import OpenAPI / Swagger
         │
         ▼
┌──────────────────────────────────────────────────────┐
│ File:  [Browse]   or   URL: https://...              │
└──────────────────────────────────────────────────────┘
         │
         ▼ (after parsing)
┌──────────────────────────────────────────────────────┐
│ Found 24 endpoints in openapi.json                   │
├───────────────┬──────────────────────────────────────┤
│ ☑ Auth (3)   │  POST  /auth/login                   │
│              │  POST  /auth/refresh                  │
│              │  DELETE /auth/logout                  │
├───────────────┼──────────────────────────────────────┤
│ ☑ Users (8)  │  GET   /users                        │
│              │  POST  /users                         │
│              │  GET   /users/{id}                    │
│              │  ...                                  │
├───────────────┴──────────────────────────────────────┤
│                                    [Import Selected] │
└──────────────────────────────────────────────────────┘
```

QAClan generates request stubs with sample bodies from the spec and auto-creates assertions based on documented response schemas.

---

### 2D — Import from Postman / Bruno

Teams migrating from Postman or Bruno can bring their existing collections in one click.

```
API → + Discover → Import Postman collection
                   (or Import Bruno files)
         │
         ▼
┌──────────────────────────────────────────────────────┐
│ Upload Postman collection JSON or .bru folder        │
│ [Browse file]                                        │
└──────────────────────────────────────────────────────┘
         │
         ▼
All requests, folders, and environments imported.
Postman test scripts preserved as-is.
Folders become QAClan collections.
Variables become environment variables.
```

---

## User Flow 3: Building Assertions (No Code)

After a request is sent, the user wants to define what "passing" means.

```
┌─────────────────────────────────────────────────────────────┐
│ ▾ Assertions                                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  [status code   ▾]  [equals      ▾]  [200      ]    [×]   │
│  [json path     ▾]  [exists      ▾]  [$.data.id]    [×]   │
│  [response time ▾]  [less than   ▾]  [500      ]ms  [×]   │
│  [header        ▾]  [contains    ▾]  [application/json] [×]│
│                                                             │
│  [+ Add assertion]                                          │
└─────────────────────────────────────────────────────────────┘
```

**Assertion types available:**
- Status code
- JSON path (pick a field deep in the response, e.g. `$.user.email`)
- Response time (milliseconds)
- Response header value
- Response body text (contains / matches)

No code needed. Point and click.

---

## User Flow 4: Sending a Request and Reading Results

```
User clicks [Send]
         │
         ▼ (loading...)
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│ Response                                                    │
│ Status: 201 Created   Time: 142ms   Size: 1.2 kb           │
├────────────────────────────────────────────────────────────-┤
│ [Body]  [Headers]  [Assertion Results]                      │
├─────────────────────────────────────────────────────────────┤
│ {                                                           │
│   "id": 42,                                                 │
│   "name": "Alice",                                          │
│   "email": "alice@example.com",                             │
│   "created_at": "2026-06-19T10:30:00Z"                     │
│ }                                                           │
└─────────────────────────────────────────────────────────────┘

[Assertion Results] tab:
┌─────────────────────────────────────────────────────────────┐
│ ✓  status code equals 200          actual: 201  ✗ FAIL      │
│ ✓  json path $.id exists           actual: 42   ✓ PASS      │
│ ✓  response time < 500ms           actual: 142ms ✓ PASS     │
└─────────────────────────────────────────────────────────────┘
```

The assertion failure (status 201 vs expected 200) is highlighted. User fixes the assertion to `201` and saves. Next run it passes.

Clicking any JSON field in the Body tab offers "Add assertion for this field" — one-click path to build assertions from real response data.

---

## User Flow 5: Organizing into Collections

```
Requests list (ungrouped)          Collections sidebar
────────────────────               ──────────────────────
POST  /auth/login                  API
GET   /auth/me                     ├── Collections
POST  /users                       │   └── (empty)
GET   /users/:id                   ├── Requests
DELETE /users/:id                  └── + Discover
POST  /orders
GET   /orders/:id

User right-clicks "POST /auth/login"
→ "Move to collection"
→ "New collection: Auth Flows"

Repeat for GET /auth/me, POST /users, etc.

Result:
                                   API
                                   ├── Collections
                                   │   ├── Auth Flows      [▶ Run] [⋯]
                                   │   │   ├── POST /auth/login
                                   │   │   └── GET  /auth/me
                                   │   └── User Management [▶ Run] [⋯]
                                   │       ├── POST /users
                                   │       ├── GET  /users/:id
                                   │       └── DELETE /users/:id
                                   ├── Requests
                                   │   └── POST /orders (ungrouped)
                                   └── + Discover
```

**[▶ Run]** runs all requests in the collection in sequence. Results shown in a lightweight panel — pass/fail per request, total time.

**[⋯]** opens collection menu: Rename / Export / Delete.

---

## User Flow 6: Building a Mixed Suite (API + Browser)

This is QAClan's unique feature. A suite can mix API requests and browser tests in any order.

```
User goes to: Suites → New Suite

┌──────────────────────────────────────────────────────────────┐
│ Suite name: Checkout Flow                                    │
│ Description: Creates test user, completes purchase, cleanup  │
├──────────────────────────────────────────────────────────────┤
│ Steps:                                                       │
│                                                              │
│  (empty — add steps below)                                   │
│                                                              │
│  [+ Add Script]    [+ Add API Request]                       │
└──────────────────────────────────────────────────────────────┘
```

User adds steps in order:

```
Step 1: [+ Add API Request] → picks "POST /users" from list
Step 2: [+ Add Script]      → picks "login-flow.py"
Step 3: [+ Add Script]      → picks "checkout.py"
Step 4: [+ Add API Request] → picks "DELETE /users/:id"
```

Suite builder now shows with **state flow indicators**:

```
┌──────────────────────────────────────────────────────────────┐
│ Suite: Checkout Flow                                         │
│ "Creates test user, completes purchase, cleanup"             │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  1. [API]  POST /users          → passes: user_id, token    │
│                                          ↓          ↓       │
│  2. [E2E]  login-flow.py        ← uses: token               │
│                                          ↓                  │
│  3. [E2E]  checkout.py          ← uses: (nothing)  ⚠        │
│                                                             │
│  4. [API]  DELETE /users/:id    ← uses: user_id             │
│                                                             │
│  [+ Add Script]    [+ Add API Request]                       │
└──────────────────────────────────────────────────────────────┘
```

The **⚠** on step 3 tells the user: "checkout.py doesn't receive anything from the previous step." This is fine — checkout.py might be self-contained. But the visual makes it obvious, so the user can consciously decide.

---

## User Flow 7: State Bridge (How Data Flows Between Steps)

This is the "magic" — values extracted from an API response automatically appear in the next step, with no copy-pasting.

```
STEP 1: POST /users
────────────────────────────────────────
Request:
  POST https://api.myapp.com/users
  Body: { "name": "Alice", "role": "tester" }

Response:
  { "id": 42, "token": "eyJhbGc..." }

Post-script (written once by the user):
  qc.set("user_id", response.json().id)     → saves 42
  qc.set("auth_token", response.json().token) → saves "eyJhbGc..."
────────────────────────────────────────
         │
         │  42 and "eyJhbGc..." are now in the shared state
         ▼

STEP 2: login-flow.py (browser test)
────────────────────────────────────────
The script reads:
  token = os.environ["QACLAN_STATE_auth_token"]  → "eyJhbGc..."
  
Uses token to skip the login form and go straight to dashboard.
────────────────────────────────────────
         │
         ▼

STEP 4: DELETE /users/:id
────────────────────────────────────────
URL: https://api.myapp.com/users/{{user_id}}
                                    ↑
QAClan fills in 42 automatically from shared state.

Result: test user deleted. No orphan data left in the test environment.
────────────────────────────────────────
```

**What the user sees:** In the suite builder, each step shows which values it writes (→) and which it reads (←). No setup required beyond the post-script on step 1.

---

## User Flow 8: Running a Suite and Reading the Unified Report

```
User opens Suite: "Checkout Flow" → clicks [Run Suite]
         │
         ▼
Run starts. Live progress:

┌──────────────────────────────────────────────────────────────┐
│ Suite Run: Checkout Flow  ●  RUNNING...                      │
├──────────────────────────────────────────────────────────────┤
│  ✓  [API]  POST /users           142ms   done               │
│  ✓  [E2E]  login-flow.py          48s    done               │
│  ●  [E2E]  checkout.py           ...     running            │
│  ○  [API]  DELETE /users/:id     —       waiting            │
└──────────────────────────────────────────────────────────────┘

Run completes:

┌──────────────────────────────────────────────────────────────┐
│ Suite Run: Checkout Flow  ●  FAILED  ●  3m 12s              │
│ "Creates test user, completes purchase, cleanup"             │
│ 3 passed  ·  1 failed                                        │
├──────────────────────────────────────────────────────────────┤
│  ✓  [API]  POST /users           142ms                       │
│  ✓  [E2E]  login-flow.py          48s                        │
│  ✗  [E2E]  checkout.py          2m 10s   ← click for trace  │
│  ✓  [API]  DELETE /users/:id      89ms                       │
└──────────────────────────────────────────────────────────────┘
```

Clicking the failed `[E2E]` step opens the Playwright trace (what the browser saw at each click). Clicking a `[API]` step expands inline:

```
▾ [API]  POST /users   142ms   ✓ PASSED
  Status: 201   Time: 142ms
  Assertions: ✓ status 201  ·  ✓ $.id exists  ·  ✓ < 500ms
  Response: { "id": 42, "name": "Alice" }
```

---

## User Flow 9: Export

User wants to share a collection with a teammate or back it up in git.

```
Collections sidebar → Auth Flows → [⋯] → Export

┌──────────────────────────────────────────────────────────────┐
│ Export: Auth Flows                                           │
│                                                              │
│ Format:  ● Bruno (.bru files — git-friendly)                 │
│          ○ Postman collection JSON                           │
│                                                              │
│ Output:  ● Download as zip                                   │
│          ○ Write to local path: [./api/auth/          ]      │
│                                                              │
│                                          [Export]            │
└──────────────────────────────────────────────────────────────┘
```

---

## Full Feature Map (User Perspective)

```
                          ┌──────────────┐
                          │  API Section  │
                          └──────┬───────┘
                                 │
             ┌───────────────────┼───────────────────┐
             │                   │                   │
     ┌───────▼──────┐   ┌────────▼───────┐   ┌──────▼──────┐
     │  Collections  │   │    Requests    │   │  + Discover  │
     └───────┬───────┘   └────────┬───────┘   └──────┬──────┘
             │                   │                   │
     [▶ Run] [Export]     [Open editor]      ┌───────┴────────┐
             │                   │           │  Import from:  │
             │            ┌──────▼──────┐    │  • Playwright  │
             │            │  Request    │    │  • HAR file    │
             │            │  Editor     │    │  • OpenAPI     │
             │            ├─────────────┤    │  • Postman     │
             │            │ URL/Method  │    │  • Bruno       │
             │            │ Params      │    └───────┬────────┘
             │            │ Headers     │            │
             │            │ Body        │     Requests created
             │            │ Auth        │     pre-filled
             │            │ Pre-script  │
             │            │ Assertions  │
             │            │ Post-script │
             │            └──────┬──────┘
             │                   │
             │              [Send] → Response + Assertion Results
             │
             └──────────────────┐
                                │
                    ┌───────────▼──────────┐
                    │   Add to Suite       │
                    │   (mix with E2E)     │
                    └───────────┬──────────┘
                                │
                    ┌───────────▼──────────┐
                    │   Suite Builder      │
                    │   with state flow    │
                    │   indicators         │
                    └───────────┬──────────┘
                                │
                            [Run Suite]
                                │
                    ┌───────────▼──────────┐
                    │   Unified Report     │
                    │   API + E2E steps    │
                    │   one timeline       │
                    └──────────────────────┘
```

---

## What Makes This Different From Postman

| Pain Point | Postman | QAClan |
|---|---|---|
| Requires cloud account | Yes — mandatory login | No — fully local |
| API tests and browser tests in one report | No — separate tools | Yes — one suite, one report |
| Data from API auto-flows into browser test | No — manual copy-paste | Yes — state bridge |
| Git-friendly export | No — JSON blob | Yes — Bruno format |
| Secrets visible in UI | Yes — plain text | No — env vars, masked |
| Test scripts | JavaScript only | JavaScript or Python |
| Find APIs from existing tests | No | Yes — capture from Playwright runs |
| Import from OpenAPI spec | Manual | Auto-generate with assertions |

---

## Out of Scope (Not in This Version)

- Mock servers (simulate API responses)
- WebSocket testing
- Load / performance testing (how many requests per second can the API handle)
- Mobile app traffic capture (proxy mode)
- Cloud sync for API requests

These can be added in future versions once core API testing is validated.
