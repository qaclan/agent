## Why

The test timeout is a flat `max(expect, action) + 60s` (90s by default). It does not grow with script length, so a long recorded flow can pass every individual wait and still fail on the total. Only `javascript_test` / `typescript_test` have a per-test timeout; raw `python` / `javascript` / `typescript` scripts are limited only by a hard-coded 300s subprocess kill used in four places.

The wait limit is configurable per run and per script, but the "Inherit suite default" choice has no suite default behind it, and there is no project settings screen. Runs record nothing about the timeouts they used, so a timeout failure cannot be explained after settings change, and nothing shows how much time a suite is allowed to take before it runs.

## What Changes

- Add a shared budget module (`cli/timeout_budget.py`) as the single source of truth for wait limit, max script time, test timeout and estimates. Runner, solo run and preview all call it.
- Test timeout becomes `auto` by default: `min(CAP, max(FLOOR, 30s + 5s * n_actions))`, with `FLOOR = max(expect, action) + 60s` so no budget gets shorter. A fixed value can override it. New env var `QACLAN_TEST_TIMEOUT` carries it to `javascript_test` / `typescript_test`.
- Max script time becomes configurable (default 280s, range 60s to 1800s). The subprocess kill derives from it (`max script time + 20s`), replacing the hard-coded `PER_SCRIPT_TIMEOUT_SEC` in all four places.
- Add project-level and suite-level `wait_timeout`, `test_timeout`, `max_script_time` (nullable; NULL means inherit / auto). Wait limit resolves script > run dialog pick > suite > project > 15000. Max script time resolves suite > project > 280000.
- New "Project settings" page (Timeouts section only), new `GET` / `PUT /api/projects/<id>/settings`, suite update route accepts the three fields.
- Run dialog wait-limit select gains a first option "Use suite default (Ns)" that sends nothing.
- Project and suite settings sync to the cloud (push and pull). Also fix the existing gap where script `wait_timeout` is pushed but never pulled.
- Record per run: JSON `timeout_config` snapshot on `suite_runs`, `effective_wait_timeout` / `effective_test_timeout` on `script_runs`. Run detail shows it; the error classifier separates `Test timeout of Nms exceeded` from an expect timeout and from the max-script-time kill.
- New `GET /api/suites/<id>/timeout-preview` plus a suite settings panel (per-script budget table, summary, warnings) and a one-line summary in the run dialog.
- Fix defects found on the way: `run_script_solo` unpacks 3 values from the 4-value `_read_artifacts`, and hardcodes `QACLAN_EXPECT_TIMEOUT` / `QACLAN_ACTION_TIMEOUT` to 15000, ignoring script `wait_timeout`. Check whether the stale `ScriptStrategy.expect_timeout = 7000` is read anywhere.

## Capabilities

### New Capabilities

- `timeout-budget`: resolution chains (wait limit, max script time), test timeout formula (auto and fixed, clamp to cap), derived subprocess kill, and runner / solo-run enforcement via `QACLAN_*` env vars.
- `timeout-settings`: project and suite timeout fields, validation, project settings page, project settings API, suite update fields, run dialog "Use suite default".
- `timeout-config-sync`: cloud push and pull of project / suite timeout fields, absent-key pull semantics, and pull of script `wait_timeout`.
- `run-timeout-record`: per-run snapshot and effective values, run detail display, timeout failure classification and `next_step` guidance.
- `timeout-budget-preview`: preview endpoint with unsaved-edit params, suite settings panel with per-script table, summary and warnings, run dialog summary line.

### Modified Capabilities

None. No existing spec in `openspec/specs/` covers run timeouts.

## Impact

- Code: `cli/timeout_budget.py` (new), `cli/db.py` (migrations), `cli/script_strategies/javascript_test_strategy.py`, `cli/script_strategies/base.py`, `cli/error_classifier.py`, `cli/sync.py`, `cli/sync_queue.py`, `cli/commands/pull.py`, `web/routes/runs.py`, `web/routes/scripts.py`, `web/routes/projects.py`, `web/routes/suites.py`, `web/static/app.js`.
- Schema: new nullable columns on `projects`, `suites`, `suite_runs`, `script_runs`. Additive only; existing runs keep NULL and the UI must handle that.
- Cloud: qaclan.com API must accept and return the three fields on projects and suites. Outside this repo. Sync is best-effort, so an agent ahead of the cloud degrades to local-only settings, but the cloud must ignore or accept unknown fields rather than reject the whole payload.
- Docs: `docs/test-timeout-budget-plan.md` and `docs/expect-timeout-strategy-plan.md` stay in step with any change to the chains, `QACLAN_TEST_TIMEOUT`, the formula or the synced fields.
- Behavior: default budgets never shrink (floor equals today's value). Scripts longer than about 12 actions get a larger test timeout. The default subprocess kill stays 300s (280s max script time + 20s).
