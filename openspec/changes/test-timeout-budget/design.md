## Context

Source plan: `docs/test-timeout-budget-plan.md` (extends `docs/expect-timeout-strategy-plan.md`). Motivation in proposal.md.

Current state that shapes the approach:

- `_render_config` in `javascript_test_strategy.py` hard-codes `timeout = max(expect, action) + 60s`. When the runner sets both env vars to the same wait limit (default 15000) the effective floor is 75s. The 90s figure only appears when the env vars are unset and the config's action fallback of 30000 applies. The floor in this design keeps the runner's value, so budgets never get shorter in real runs.
- `PER_SCRIPT_TIMEOUT_SEC = 300` in `web/routes/runs.py` is used for `subprocess.run(timeout=)` in `runs.py` and `scripts.py`, the "timed out after Ns" message, and the classifier text.
- `runs.py` already resolves a run-level wait limit and sets `QACLAN_EXPECT_TIMEOUT` / `QACLAN_ACTION_TIMEOUT` per script. `run_script_solo` does not: it hardcodes 15000 and unpacks 3 values from a 4-value `_read_artifacts`.
- Migrations follow the `_migrate_script_wait_timeout` pattern in `cli/db.py`. Cloud push adds a field only when non-NULL (`sync_script_to_cloud`).
- No automated tests exist. Verification is manual.

## Goals / Non-Goals

**Goals:**

- One Python module owns every budget calculation, so runner, solo run and preview cannot drift.
- Additive schema and payload changes only; old rows, old agents and old cloud responses keep working.
- Defaults never make any budget shorter than today's.

**Non-Goals:**

- No global (cross-project) settings layer.
- No sync of run snapshots to the cloud (follow-up; needs the cloud change).
- No change to how `selectOption` is handled by the Review & Improve wizard (tracked separately).
- No automated test suite introduced.

## Decisions

### Single budget module

`cli/timeout_budget.py` exposes resolvers (wait limit, max script time, each returning value plus winning level), a step counter, the test timeout calculation, an estimator and the subprocess timeout. `BASE` (30s) and `PER_ACTION` (5s) are named constants in that file.

Alternative: compute in JS for the preview. Rejected: two implementations drift, and the preview exists to match the run.

### Test timeout is computed by the runner, delivered by env var

The runner computes the value and exports `QACLAN_TEST_TIMEOUT`; the generated Playwright config reads it and falls back to the old flat formula when unset.

Alternative: embed the number in the generated config at codegen time. Rejected: the value depends on suite, project and run pick, which change after a script is recorded.

### Action counting is static text matching in the strategy's own syntax

`count_steps` scans the action block for the listed call forms (goto, click, fill, selectOption, check/uncheck, press, hover, dblclick) and settle markers via the strategy's existing settle marker.

Alternative: instrument at run time. Rejected: the budget must exist before the run starts, and the preview needs it without executing anything. Trade-off: scripts that build actions in loops or helpers are under-counted, which the floor absorbs.

### Max script time drives the subprocess kill

Kill = max script time + 20s, so the in-process test timeout (capped at max script time) always fires first and produces a precise message. Default 280s keeps the effective kill at 300s.

Alternative: keep 300s fixed and only cap the test timeout. Rejected: raising max script time above 300s would then be silently ineffective.

### Inheritance stored as NULL, resolved at run time

Project and suite columns are nullable; NULL means inherit (or auto for test timeout). Nothing is copied down, so changing a project default affects every inheriting suite.

Alternative: snapshot defaults into suites on creation. Rejected: surprising drift and no way to express "inherit".

### Clamp rather than reject when the cap drops later

Validation on save checks fixed test timeout against the resolved max script time at that moment. A later lower-level change can still invalidate it, so run time clamps and the preview warns.

Alternative: cascade-validate on every save. Rejected: a suite edit would fail because of a project value the user is not editing.

### Run dialog "Use suite default" sends nothing

Absence of a pick, not a number, is what lets suite and project defaults take effect. A numeric pick stays a one-off override.

### Cloud payload: add only non-NULL fields; pull only present keys

Mirrors the existing script pattern. Push of untouched entities is byte-identical to today. Pull treats key presence as authoritative, null as clear, absence as no-op, so an older cloud cannot wipe local settings.

### Snapshot as JSON text plus two typed columns

`suite_runs.timeout_config` holds the explanatory snapshot (levels included); `script_runs.effective_*` are typed for querying calibration data.

Alternative: normalise into a table. Rejected as overkill for display and analysis by SQL.

### Phasing

Phase 0 (solo unpack fix) and phase 1 (module, env var, runner wiring, built-in defaults, no schema) ship independently of later phases. Phases follow the plan's order 0 to 6; see tasks.md.

## Risks / Trade-offs

- [Cloud rejects unknown fields on projects or suites, stopping name sync too] → Confirm cloud behavior before shipping phase 3; sync is best-effort so the agent degrades to local-only, and the cloud change ships first.
- [Action counter misses loops or helper-built actions, giving a short auto budget] → The floor equals today's value, fixed test timeout is available, and the preview exposes counts so users can see them.
- [Calibration rests on 62 runs from one machine] → Treat constants as provisional; re-run the history query before phase 1 ships and after a week of use (run snapshots make this routine).
- [A higher cap lets a hung test burn more time before failing] → Cap stays user-chosen and defaults to 280s; the preview shows suite totals.
- [Push omits NULL fields, so clearing a setting locally (back to inherit/auto) never reaches a cloud that already holds the old value; a later pull with the key present would restore it] → Accepted to keep untouched payloads identical (matches script `wait_timeout`). If this bites, send explicit nulls for entities that already have a `cloud_id`; decide with the cloud contract.
- [Preview and runner diverge] → Both call the same module; verification step compares preview values with what the runner logs.
- [Stale `ScriptStrategy.expect_timeout = 7000` misleads] → Grep for readers during phase 1; remove if unused, otherwise align.

## Migration Plan

1. Migrations add nullable columns only; they run on startup via the existing `_run_migrations()`. No backfill.
2. Rollback: older code ignores the new columns. The cloud-side change ships before phase 3 is released.
3. Existing runs keep NULL snapshot and effective values; every reader tolerates NULL.

## Open Questions

- Cloud contract: exact field names, null handling and unknown-field behavior on qaclan.com (needs the cloud owner; does not change this agent's design, only phase 3 timing).
- Whether to sync run snapshots to the cloud later.
