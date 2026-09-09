## Why

A post-script `qc.set('key', value)` (e.g. capturing `access_token` from a login response) persists into the collection's variable store keyed only by `collection_id`, overwriting the user's static collection-var default and taking precedence over the environment variable of the same name in every future run — regardless of which environment is active. Switching environments or unsetting the environment entirely does not invalidate the script-captured value, so a request keeps authenticating with a stale token from a different environment. This also makes the variable picker look like it has a duplicate `access_token` (one under the environment, one under the collection) with no indication one was silently produced by a script run.

## What Changes

- Collection variables gain two storage layers: the existing `initial_value` (pure user-authored static default, never touched by scripts) and a new runtime override (`runtime_value` + `runtime_env_name`) written only by `qc.set`/script output.
- `qc.set` output is now tagged with the environment that was active when the script ran, instead of being written as an untagged, environment-agnostic override.
- When seeding a run's variables, a collection variable's runtime override is used only if its tagged environment matches the collection's currently active/bound environment; otherwise the seed falls back to the static `initial_value` (or is absent).
- Switching the collection's bound environment, or unsetting it, causes any previously captured runtime override tied to a different (or no) environment to stop applying automatically — no code path needs to explicitly "clear" it.
- The variable picker / collection-vars UI surfaces, for a variable with an active runtime override, that its current value came from a script run under a specific environment, distinct from the static default.
- Runtime variable precedence itself (collection/runtime value over environment value, within a matching environment) is unchanged — only the scoping of what counts as "the collection's current value" changes.
- `docs/api-script-reference.md`'s persistence section is updated to document the per-environment scoping of `qc.set` persistence (required by this repo's script-behavior documentation maintenance rule).

## Capabilities

### New Capabilities
- `collection-runtime-variables`: Defines how a post/pre-script's `qc.set` output is persisted per collection, scoped to the environment active at capture time, seeded back into later runs only when that same environment is still active, and kept separate from the collection's user-authored static variable defaults.

### Modified Capabilities
- `api-environment-selection`: The existing requirement "Run-time variable precedence is unchanged" (scenario: collection variable beats environment variable of the same key) is refined — precedence still favors the collection's current value, but that current value is now itself scoped to the active environment via `collection-runtime-variables`, so switching or unsetting the environment changes which value is "current."

## Impact

- `cli/db.py`: new migration adding `runtime_value` / `runtime_env_name` columns to `collection_vars`.
- `web/api/repositories/collection_vars_repo.py`: new `upsert_runtime()`, `as_seed_dict()` gains an `env_name` parameter and matching logic; existing `upsert()` (static default editing) unchanged.
- `web/api/services/runner_service.py`: post-script persistence call switches from `upsert()` to `upsert_runtime()` with the resolved `env_name`; all `as_seed_dict()` call sites pass `env_name` through.
- `cli/api_runner.py`: no change to `resolve_vars()` precedence logic — only the seed data feeding it changes upstream.
- Variable picker / collection-vars UI (under `web/static/api/`): surfaces runtime-override-vs-static-default and its source environment.
- `docs/api-script-reference.md`: persistence section updated per the maintenance rule in `CLAUDE.md`.
- No automated tests exist in this repo; verification is manual (documented in tasks).
