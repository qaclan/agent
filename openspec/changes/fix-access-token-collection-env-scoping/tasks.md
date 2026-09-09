## 1. Schema

- [x] 1.1 Add migration in `cli/db.py` (alongside `_migrate_var_picker`, `cli/db.py:324-334`) adding `runtime_value TEXT DEFAULT NULL` and `runtime_env_name TEXT DEFAULT NULL` to `collection_vars`.

## 2. Repository layer

- [x] 2.1 Add `CollectionVarsRepo.upsert_runtime(collection_id, key, value, env_name)` in `web/api/repositories/collection_vars_repo.py` — writes only `runtime_value`/`runtime_env_name`, never `initial_value`; encrypts if the variable is marked secret, matching the existing `upsert()` behavior.
- [x] 2.2 Update `CollectionVarsRepo.as_seed_dict()` to accept `env_name`: for each row, use `runtime_value` if `runtime_env_name == env_name`, else fall back to `initial_value` (omit the key if neither is set). Decrypt secrets same as today.
- [x] 2.3 Leave existing `upsert()` (`collection_vars_repo.py:23-60`) untouched — still the write path for the manual var-picker UI's static defaults.

## 3. Runner service wiring

- [x] 3.1 In `web/api/services/runner_service.py`, `resolve_and_run_api_item()` gains an `env_name` param; the persistence call now uses `vars_repo.upsert_runtime(req["collection_id"], key, str(value), env_name=env_name)` instead of `upsert(...)`. All 3 call sites (`run_request`, `_execute_collection`, `run_collection`) pass `env_name=env_name` through. Also updated the 4th call site in `web/routes/runs.py` (suite-run API items), which shares this function.
- [x] 3.2 Updated all `as_seed_dict(collection_id)` call sites to pass the resolved `env_name` through: `runner_service.py` (`run_request`, `run_negatives`, `_execute_collection`) and `runs.py` (suite API-item seeding). `run_collection` doesn't call `as_seed_dict` — it only seeds from a caller-supplied `seed_vars` dict, unchanged.
- [x] 3.3 Confirmed: `env_name` is resolved via `col.get("env_name")` fallback in `run_request`/`run_negatives`/`plan_request_negatives`; `start_collection_run`/`_execute_collection` take `env_name` only from the caller argument (no server-side fallback to `col.env_name`) — pre-existing behavior, not introduced by this change. The frontend (`collections-view.js`) already resolves and passes `col.env_name` explicitly for collection runs, so this holds in practice; no code change made here.

## 4. Variable picker UI

- [x] 4.1 Located: `web/static/api/views/collection-detail-view.js` (`_buildVarsTab`/`_addVarRow`), fed by `GET /api/collections/<id>/vars` in `web/api/routes/collections.py`.
- [x] 4.2 Route now computes `runtime_active` (`runtime_value` set and `runtime_env_name` matches the collection's bound `env_name`) per var and masks `runtime_value` for secrets alongside `initial_value`. The row renderer shows a "live" badge next to the value input when `runtime_active` is true, with a tooltip naming the capturing environment; the input itself always shows/edits the static default.

## 5. Documentation

- [x] 5.1 Updated `docs/api-script-reference.md`: the persistence section now documents the env-scoped `runtime_value`/`runtime_env_name` mechanism and the fallback-to-static-default behavior; the "Known gaps" 4-tier-scoping note now cross-references it.

## 6. Manual verification

- [x] 6.1 Verified at the data layer (isolated temp `~/.qaclan` DB, not the real one): static default `access_token` set, `upsert_runtime(..., env_name="dev")` simulating a script capture, `as_seed_dict(col_id, "dev")` returns the captured value. PASS.
- [x] 6.2 Same setup, `as_seed_dict(col_id, "staging")` (different bound env) falls back to the static default instead of the stale "dev" capture. PASS.
- [x] 6.3 Same setup, `as_seed_dict(col_id, None)` (env unbound) also falls back to the static default. PASS.
- [x] 6.4 After `upsert_runtime`, `initial_value` in the DB row is confirmed unchanged (`STATIC_DEFAULT_TOKEN`), `runtime_value`/`runtime_env_name` stored separately. PASS. Also verified a capture made with no environment bound (`env_name=None`) only reapplies when unbound again, not under a different bound environment.
- [x] 6.5 Verified the `list_collection_vars` route transform directly: for a secret variable with a matching-env runtime override, `runtime_active` is `True` and both `initial_value` and `runtime_value` are masked in the response. PASS. The frontend "live" badge/tooltip logic (`collection-detail-view.js`) was implemented to key off `runtime_active`/`runtime_env_name` but was **not** visually confirmed in a running browser — this repo has no dev server smoke-tested as part of this task; recommend a quick manual look in `qaclan serve` before merge.

Verification script (not part of the repo, scratch only): ran against an isolated temp `HOME` so the real `~/.qaclan/qaclan.db` was never touched.
