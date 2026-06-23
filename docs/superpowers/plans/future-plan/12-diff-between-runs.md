# 12 - Diff Between Runs

Deep-dive on feature #12 from [feature-ideas.md](../feature-ideas.md). Covers what we can diff today, what we need to add, and the performance implications of storing per-run snapshots.

---

## The problem

"It passed yesterday. It fails today. What changed?"

This is the most common debugging question after a regression. QAClan currently stores: status, error message, step results, one screenshot (on failure). There is no way to compare two runs side by side. The user has to mentally reconstruct what changed between a passing run and a failing one.

## Example

```
Run A (Monday — PASSED):  checkout-flow
Run B (Tuesday — FAILED): checkout-flow

Current: user reads error_message: "locator '#pay-btn' timeout". Guesses.

With diff view:
  Screenshot diff: 
    Monday screenshot — modal was absent
    Tuesday screenshot — modal overlay present, covering #pay-btn
  
  Network diff:
    Monday — POST /api/payment returned 200 in 340ms
    Tuesday — POST /api/payment returned 503 (backend error triggered modal)
  
  DOM diff (optional, requires snapshot):
    A new <div class="error-modal"> present only in Tuesday run

User sees in 30 seconds: "A new modal appeared. Backend is returning 503."
```

## Impact

| Dimension | Effect |
|---|---|
| Regression root-cause | Reduces guessing. Diff shows exactly what changed between last pass and current fail. High. |
| Screenshot diff value | Catches visual regressions that don't cause test failures (e.g. button moved but still clickable). |
| Network diff value | Surfaces API changes that cause test behavior changes. Often the real root cause. |
| Storage cost | Significant. Per-run DOM + network snapshots = 10–50MB per suite run. Trade-off needs a retention policy. |

Overall: **high impact** for debugging, **medium cost** due to storage. Scope carefully.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **Playwright `toHaveScreenshot()`** | Visual regression assertion: fails if screenshot differs from baseline. | Opt-in per assertion. User must write the assertion. Baseline is a file, not a prior run. No diff UI built in. |
| **Percy (BrowserStack)** | Visual diff platform. Compares screenshots across builds. | Cloud, paid. Only visual. No network or DOM diff. Separate tool, not integrated into test results. |
| **Applitools Eyes** | AI-powered visual diff. | Cloud, paid. Very expensive. |
| **Chromatic** | Visual diff for Storybook components. | Storybook only. Not E2E. |
| **Currents.dev** | Shows run history. No diff UI. | Cannot compare two specific runs. |

**Our diff:** Run-to-run diff inside QAClan's existing run history. Covers screenshots, network logs, step timing. No external tool, no cloud, no extra assertion writing. Triggered on demand from the "Compare" button — no overhead when not needed.

## What we can diff today vs what needs to be added

Already stored per `script_run`:
- `screenshot_path` — one screenshot (failure only)
- `console_log` — text blob
- `network_log` — text blob (format TBD)
- `error_message` / `error_detail`
- `step_runs` — per-step status, duration, error

Need to add for meaningful diff:
- Screenshot at each step (not just failure) — to see exactly when state diverged
- Structured network log (JSON: method, url, status, duration) for diff rendering
- DOM snapshot at failure point (full HTML or key element subtree)

## Scope for v1 (minimum useful diff)

Start with what we already have:

1. **Screenshot diff** — single failure screenshot from each run. Pixel diff overlay using PIL/Pillow. Good enough to spot "new modal appeared" or "layout shift".
2. **Step timing diff** — table of step N from run A vs run B: which steps took longer, which status changed. Catches performance-induced flakes.
3. **Error diff** — error_message from each run. Simple text comparison. Shows if the error changed at all.

Full DOM and per-step screenshots are Phase 2 — higher storage cost, higher implementation effort.

## Screenshot diff implementation

Use Python's Pillow library (already likely in the environment or easy to add):

```python
from PIL import Image, ImageChops
import io

def diff_screenshots(path_a, path_b):
    img_a = Image.open(path_a).convert("RGB")
    img_b = Image.open(path_b).convert("RGB")
    
    # Resize to same dimensions if needed
    if img_a.size != img_b.size:
        img_b = img_b.resize(img_a.size)
    
    diff = ImageChops.difference(img_a, img_b)
    # Enhance diff for visibility
    diff_enhanced = diff.point(lambda p: p * 10)
    
    return {
        "changed_pixels": sum(1 for p in diff.getdata() if p != (0, 0, 0)),
        "total_pixels": img_a.size[0] * img_a.size[1],
        "diff_image_b64": _to_base64(diff_enhanced)
    }
```

Render three panels in UI: Run A screenshot | Diff overlay | Run B screenshot.

## Step timing diff

```python
# Compare step durations
steps_a = {s["order_index"]: s for s in script_run_a["steps"]}
steps_b = {s["order_index"]: s for s in script_run_b["steps"]}

for idx in set(steps_a) | set(steps_b):
    a = steps_a.get(idx, {})
    b = steps_b.get(idx, {})
    yield {
        "index": idx,
        "action": a.get("action") or b.get("action"),
        "duration_a": a.get("duration_ms"),
        "duration_b": b.get("duration_ms"),
        "status_a": a.get("status"),
        "status_b": b.get("status"),
        "delta_ms": (b.get("duration_ms") or 0) - (a.get("duration_ms") or 0)
    }
```

## Schema — no changes needed for v1

v1 diff uses existing `script_runs` and `step_runs` data. No new storage.

v2 additions:
```sql
ALTER TABLE script_runs ADD COLUMN step_screenshots TEXT;
-- JSON array: [{step_index, screenshot_b64}] or paths to files
ALTER TABLE script_runs ADD COLUMN dom_snapshot TEXT;
-- HTML string of page at failure point
```

## Implementation path

### Phase 1 — compare UI + screenshot diff

- UI: "Compare" button on script detail page. Shows run history list with checkboxes. User picks two runs. Opens diff view.
- Flask route: `GET /api/runs/diff?run_a=<id>&run_b=<id>` — returns diff payload.
- Compute: screenshot diff (Pillow), step timing diff (Python), error diff (string compare).
- Render: side-by-side screenshot panels + step comparison table.

### Phase 2 — per-step screenshots

- Harness: capture screenshot after each step (configurable: only on status change, always, only on fail).
- Store as files in run dir. Paths stored in `step_runs.screenshot_path` (new column).
- Diff view: add per-step screenshot strips for granular visual diff.

### Phase 3 — DOM snapshot diff

- Harness: capture `page.content()` (full HTML) at failure point. Write to `dom_snapshot.html` in run dir.
- Diff view: HTML diff using Python `difflib.unified_diff`. Render as side-by-side code blocks with highlights.
- Storage concern: HTML can be 500KB+. Compress with gzip. Keep only on failure, auto-delete after 30 days.

## Open questions

- **Which two runs to compare?** Default suggestion: latest FAILED vs latest PASSED. Let user override. "Auto-compare with last passing run" is the 90% use case.
- **Cross-script comparison.** Sometimes you want to compare run A on script X with run B on script Y (same test, different branch). Out of scope for v1 — same script only.
- **Storage budget.** Per-step screenshots could be 20–50MB per suite run. Only capture on explicit "capture mode" toggle, not by default.

## Next concrete step

Build the diff view UI + Flask route for Phase 1 using existing data (no new data collection). That alone delivers value — users can compare step timings and error messages. Per-step screenshots come after validating the diff UX is useful.
