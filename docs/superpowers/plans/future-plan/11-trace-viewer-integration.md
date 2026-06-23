# 11 - Trace Viewer Integration

Deep-dive on feature #11 from [feature-ideas.md](../feature-ideas.md). Covers what we already capture, what we need to add (trace.zip), and how to embed the viewer without shipping a full Playwright server.

---

## What we already have

[cli/db.py](../../cli/db.py) and [web/routes/runs.py](../../web/routes/runs.py) already collect per-script-run:

- `screenshot_path` — terminal screenshot on failure.
- `console_log` — captured stdout/stderr from browser.
- `network_log` — network activity during the run.
- `error_message` / `error_detail` — structured error with category, title, selector, timeout.
- `step_runs` table — per-step action, locator, status, duration_ms, error_message.

What is **missing** for trace viewer integration:

- `trace.zip` — Playwright's binary trace file containing DOM snapshots, action timeline, network HAR, console log, and screenshots at each step.
- A way to serve or render the trace in the web UI.

## Example

```
Run: "checkout-flow" — FAILED
Failed at step 9: locator '#pay-btn' timeout

Current debug flow:
  User looks at screenshot → sees a modal overlay → guesses what happened

With trace viewer:
  Click "View Trace" on run detail page
  → Embedded iframe opens trace viewer
  → User scrubs timeline to step 8
  → Sees: modal appeared in step 7 (captured in DOM snapshot)
  → Sees: #pay-btn is behind the modal (visible in DOM panel)
  → Knows the fix immediately: close modal before clicking pay
```

## Impact

| Dimension | Effect |
|---|---|
| Debugging speed | Replace "guess from screenshot" with "see exactly what happened at every step". High. |
| MTTR (mean time to repair) | Cutting from 30-minute debug sessions to 5-minute trace reviews is realistic. |
| Value over raw Playwright | Playwright trace viewer exists but requires manual `playwright show-trace trace.zip`. QAClan surfaces it inline, zero extra steps. |
| Onboarding | New users understand test failures without knowing Playwright internals. |

Overall: **high impact** for a relatively low implementation cost, since Playwright already generates traces — we just need to enable and display them.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **Playwright HTML Reporter** | Generates an HTML report with embedded trace viewer after `--reporter=html`. | Requires test run with Reporter flag. Separate HTML file. Cannot browse from QAClan. |
| **trace.playwright.dev** | Web app that opens a local trace.zip file from disk (via file picker). | Manual: user finds the file, opens browser tab, picks file. Not integrated. |
| **Currents.dev** (paid) | Hosts Playwright traces in cloud. Shows in their dashboard. | Cloud upload required. Paid. Not local-first. |
| **`playwright show-trace`** | Opens a local server + browser window for a trace file. | Separate process. Separate window. No integration with run history. |

**Our diff:** Trace appears in the QAClan run detail page, linked directly to the failed script run. No manual file hunting. No separate window. Part of the existing run history flow.

## Approach options

### Option A — embed trace.playwright.dev via iframe

Playwright maintains a public trace viewer at `trace.playwright.dev`. It accepts a `?trace=<url>` query parameter pointing to a hosted trace file.

```html
<!-- serve trace file from Flask, load viewer from trace.playwright.dev -->
<iframe src="https://trace.playwright.dev/?trace=http://localhost:7823/api/traces/abc123"></iframe>
```

Pros: zero maintenance of the viewer code.

Cons: requires internet access (the iframe loads JS from trace.playwright.dev). Breaks offline. Cross-origin issues if trace.playwright.dev changes its CSP.

### Option B — bundle the static trace viewer locally

Playwright's trace viewer is open source. The static build (HTML + JS + CSS) can be copied and served by Flask under `/static/trace-viewer/`.

```python
# Flask route
@app.route("/traces/<run_id>")
def serve_trace(run_id):
    return send_from_directory("static/trace-viewer", "index.html")

@app.route("/api/traces/<run_id>/data")
def trace_data(run_id):
    path = resolve_trace_path(run_id)
    return send_file(path, mimetype="application/zip")
```

Pros: fully offline. No external requests. Consistent version.

Cons: adds ~5MB to the repo/binary. Must update when Playwright viewer changes.

### Decision

**Option B (local bundle) for v1.** QAClan is local-first. The trace viewer must work offline. Update the bundle when cutting a Playwright version bump. The ~5MB cost is acceptable — users already download Playwright browsers.

## Trace file capture

Currently scripts run with no trace config. Add trace recording to the script harness template for each strategy in [cli/script_strategies/](../../cli/script_strategies/).

Python harness addition:
```python
await context.tracing.start(screenshots=True, snapshots=True, sources=True)
# ... test steps ...
await context.tracing.stop(path=os.environ["QACLAN_TRACE_PATH"])
```

JS/TS harness addition:
```javascript
await context.tracing.start({ screenshots: true, snapshots: true });
// ... test steps ...
await context.tracing.stop({ path: process.env.QACLAN_TRACE_PATH });
```

`QACLAN_TRACE_PATH` set by the runner in [web/routes/runs.py](../../web/routes/runs.py) alongside `QACLAN_SCREENSHOT_PATH`.

Trace files land at: `~/.qaclan/runtime/runs/<run_id>/trace-<script_run_id>.zip`

## Schema changes

```sql
-- Migration: add trace_path to script_runs
ALTER TABLE script_runs ADD COLUMN trace_path TEXT;
```

## Implementation path

### Phase 1 — capture traces

- Add `QACLAN_TRACE_PATH` env var to runner in [web/routes/runs.py](../../web/routes/runs.py).
- Update harness templates in each strategy to call `tracing.start/stop`.
- Add `trace_path` migration to [cli/db.py](../../cli/db.py).
- Store trace path in `script_runs` after run completes.

### Phase 2 — serve + display

- Flask route: `GET /api/traces/<script_run_id>` — sends the zip file.
- Flask route: `GET /traces/<script_run_id>` — serves bundled trace viewer HTML.
- Run detail UI: "View Trace" button appears when `trace_path` is non-null. Opens trace viewer in a new tab (or modal iframe).

### Phase 3 — bundle maintenance

- Extract Playwright trace viewer static build into `web/static/trace-viewer/`.
- Add version comment at top of viewer index.html: `<!-- Playwright trace viewer vX.Y.Z -->`.
- Document update procedure in CLAUDE.md.

## Storage cost

Average trace.zip: 1–5MB per script run. For a 20-script suite: 20–100MB per run. For daily runs: 1–3GB/week. This grows fast.

Retention policy options:
- Keep traces for 30 days (default). CLI command: `qaclan cleanup --traces --older-than 30d`.
- Keep traces only for failed runs (reduces storage by ~80% for healthy suites).
- User-configurable retention in settings.

Start with "failed runs only" as default. Add full-trace option as opt-in.

## Open questions

- **Trace viewer version pinning.** Bundle from Playwright `vX.Y.Z`. When the user upgrades Playwright runtime via `qaclan setup`, do we auto-update the viewer bundle? Viewer and runtime should be in sync — mismatches can cause format errors. Pin viewer bundle version to match `PINNED_PLAYWRIGHT_VERSION` in [cli/runtime_setup.py](../../cli/runtime_setup.py).
- **Binary size.** Adding 5MB trace viewer bundle to the Nuitka binary. Check if Nuitka's `--include-data-dir` handles this cleanly. Already used for `cli/runtime_assets/` so should be fine.
- **Multi-language trace format.** Python and JS/TS Playwright both produce the same trace.zip format. Verified — trace format is engine-level, not language-level. Safe.

## Next concrete step

Add `QACLAN_TRACE_PATH` to runner env in [web/routes/runs.py](../../web/routes/runs.py). Update Python harness template in [cli/script_strategies/](../../cli/script_strategies/) with `tracing.start/stop`. Add `trace_path` migration. Verify trace.zip lands on disk after a test run before wiring any UI.
