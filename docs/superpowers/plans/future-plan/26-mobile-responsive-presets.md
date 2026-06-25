# 26 - Mobile / Responsive Presets

Deep-dive on feature #26 from [feature-ideas.md](../feature-ideas.md). Covers the device profile concept, the matrix run model, and how this differs from Playwright's built-in device emulation.

---

## The problem

E2E tests are typically written on a desktop monitor with a 1280×720 or 1920×1080 viewport. The test passes. The dev ships. On mobile, the login link is hidden in a hamburger menu that the test never opened. Test was green; users on mobile are stuck.

Without responsive testing, mobile bugs reach production regularly. Fixing them after the fact costs more than catching them in the test suite.

## Example

```
Script: "login-flow"
Run matrix: 4 device presets

Device           Width   Height  Result    Screenshot
─────────────────────────────────────────────────────
Desktop 1080p    1920    1080    ✅ PASS
iPhone 14 Pro    390     844     ❌ FAIL   [mobile menu hides login link]
iPad Air         820     1180    ✅ PASS
Galaxy S23       360     780     ❌ FAIL   [login button below fold, not scrolled]

2 of 4 devices failed. Mobile bugs caught before ship.
```

## Impact

| Dimension | Effect |
|---|---|
| Mobile bug catch rate | High. Mobile bugs are common, rarely caught by desktop-only tests. |
| Test ROI | One script tests 4 platforms instead of 1. 4x coverage for authoring one test. |
| Responsive confidence | Teams can claim "we tested on mobile" with data instead of "we assumed it works". |
| Visual evidence | Per-device screenshots show exactly how the page looks on each viewport. |
| Differentiation | Most QAClan users probably don't test mobile. This feature changes that without extra scripts. |

Overall: **high impact** for any product with mobile users (most web products). Unique feature — Playwright supports it technically but makes the matrix view manual.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **BrowserStack / Sauce Labs** | Real device cloud testing. Paid. Slow. Expensive. | Cloud dependency. Cost per minute. Complex setup. |
| **Playwright `devices` config** | `playwright.config.ts` with `projects: [{use: devices["iPhone 14"]}]`. Runs tests in device mode. | Config-only. No UI. No matrix result view. Each device = separate project = separate runner invocation. |
| **Cypress viewport** | `cy.viewport("iphone-6")` inside tests. | Per-test, in code. No matrix run across all tests. No result grid. |
| **Chrome DevTools** | Toggle device mode manually for visual inspection. | Not automated. Not integrated into test runs. |

**Our diff:** Device profiles configured in QAClan UI. Matrix run = one button → runs the same script against all selected profiles → shows a grid of results with per-device screenshots. No config changes to scripts. No separate runner invocations managed manually.

## Device Profile concept

A Device Profile is a named set of run parameters:

```json
{
  "name": "iPhone 14 Pro",
  "width": 390,
  "height": 844,
  "device_scale_factor": 3,
  "is_mobile": true,
  "has_touch": true,
  "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15..."
}
```

Profiles are used during run creation. Scripts do not need any changes — they run in Playwright with the specified emulation settings.

## Built-in preset library

QAClan ships with presets derived from Playwright's `devices` registry (open source, maintained by Playwright team). No need to copy-paste viewport dimensions.

| Preset | Width | Height | Notes |
|---|---|---|---|
| Desktop 1080p | 1920 | 1080 | Standard desktop |
| Desktop 1280 | 1280 | 720 | Minimum desktop |
| iPhone 14 Pro | 390 | 844 | Current iPhone |
| iPhone SE | 375 | 667 | Small phone |
| iPad Air | 820 | 1180 | Tablet |
| Galaxy S23 | 360 | 780 | Android mid-range |
| Galaxy Tab S7 | 800 | 1280 | Android tablet |

Users can add custom profiles (e.g. their specific product's TV viewport at 1280×720 or wearable at 320×320).

## Schema

```sql
CREATE TABLE device_profiles (
    id                  TEXT PRIMARY KEY,
    project_id          TEXT REFERENCES projects(id) ON DELETE CASCADE,
    -- NULL project_id = built-in global preset
    name                TEXT NOT NULL,
    width               INTEGER NOT NULL,
    height              INTEGER NOT NULL,
    device_scale_factor REAL DEFAULT 1.0,
    is_mobile           INTEGER DEFAULT 0,
    has_touch           INTEGER DEFAULT 0,
    user_agent          TEXT,
    is_builtin          INTEGER DEFAULT 0,
    created_at          TEXT NOT NULL
);

-- Matrix run: which profiles were selected for a suite_run
ALTER TABLE suite_runs ADD COLUMN device_profile_ids TEXT;
-- JSON array of profile IDs: '["desktop-1080", "iphone-14"]'
```

## How matrix runs work

Current: one `suite_run` → runs all scripts sequentially → one `script_run` per script.

Matrix: one `suite_run` → for each device profile × script combination → one `script_run`.

Option A: one `suite_run` per device profile (N suite_runs for N profiles).

Option B: one `suite_run` with N×M `script_run` rows (profile stored per `script_run`).

**Option B is better.** One suite_run per matrix invocation. Cleaner history. Result grid = aggregate within one suite_run.

Schema additions:
```sql
ALTER TABLE script_runs ADD COLUMN device_profile_id TEXT;
ALTER TABLE script_runs ADD COLUMN device_profile_name TEXT;
-- Denormalize name for historical accuracy (if profile is later renamed/deleted)
```

## Runner changes

In [web/routes/runs.py](../../web/routes/runs.py), the `execute_run` function iterates `suite_items`. With matrix:

```python
for item in suite_items:
    for profile in selected_profiles:
        # Set Playwright viewport/user-agent for this run
        env["QACLAN_VIEWPORT_WIDTH"] = str(profile["width"])
        env["QACLAN_VIEWPORT_HEIGHT"] = str(profile["height"])
        env["QACLAN_IS_MOBILE"] = "1" if profile["is_mobile"] else "0"
        env["QACLAN_USER_AGENT"] = profile.get("user_agent", "")
        # Run the script
        run_script(item, env, profile_id=profile["id"])
```

Harness templates read these env vars and apply them to `browser.new_context()`:

```python
context = await browser.new_context(
    viewport={"width": int(os.environ.get("QACLAN_VIEWPORT_WIDTH", 1280)),
               "height": int(os.environ.get("QACLAN_VIEWPORT_HEIGHT", 720))},
    is_mobile=os.environ.get("QACLAN_IS_MOBILE") == "1",
    user_agent=os.environ.get("QACLAN_USER_AGENT") or None,
)
```

## Matrix result view UI

Suite run detail page with matrix layout:

```
              Desktop   iPhone 14  iPad Air  Galaxy S23
login-flow      ✅         ❌          ✅          ❌
checkout        ✅         ✅          ✅          ✅
password-reset  ✅         ⚠️ retry    ✅          ✅
```

Click any cell → opens script_run detail for that script + device combination.
Click device column header → filter to that device's results only.
Click script row → filter to that script's results across all devices.

## Implementation path

### Phase 1 — built-in profiles + single device run

- Seed `device_profiles` table with built-in presets on DB init.
- Suite run UI: "Device" selector (defaults to current viewport / desktop).
- Runner passes viewport env vars. Harness applies them.
- Single device only — no matrix yet. This adds responsive testing without the matrix complexity.

### Phase 2 — matrix run

- Suite run UI: "Devices" multi-select. Pick 1–N profiles.
- Runner iterates profiles × scripts.
- Add `device_profile_id` and `device_profile_name` to `script_runs`.
- Suite run detail: matrix result grid.

### Phase 3 — custom profiles

- "Device Profiles" tab in project settings.
- Create/edit/delete custom profiles.
- Built-in presets read-only but can be cloned and customized.

### Phase 4 — matrix performance

- Matrix runs can be slow: 4 devices × 20 scripts = 80 script_runs sequentially.
- Combine with feature #7 (Parallel Run Groups): run device × script combinations in parallel where isolation allows.

## Open questions

- **Touch events.** Setting `has_touch: true` enables touch simulation. Does this break existing scripts that use `click()`? No — Playwright's `click()` works for both mouse and touch. But scripts using `mouse.move()` or hover may behave differently on touch. Document this.
- **Retina (high DPI) screenshots.** `device_scale_factor: 3` means the screenshot is 3× the CSS resolution. Screenshot comparison (feature #12 diff) needs to normalize for scale before comparing.
- **Run time cost.** 4 devices × 20 scripts × 2 minutes each = 160 minutes. Make the matrix device count selection prominent. Add a warning: "4 devices × 20 scripts = up to 80 runs estimated time: 2h 40m."
- **Mobile-specific failures.** If 3 of 4 devices fail with the same error, it is a mobile issue. If only 1 device fails, it is a specific breakpoint issue. Add a "failure pattern" summary: "2 failures share the same error — likely a mobile layout bug."

## Next concrete step

Seed built-in device profiles in [cli/db.py](../../cli/db.py) init. Add `device_profile_id` and viewport env vars to `suite_runs` migration and runner in [web/routes/runs.py](../../web/routes/runs.py). Update Python harness to read viewport env vars. Add device selector to suite run UI. Ship Phase 1 (single device) first — validate the UX and harness changes before building the matrix.
