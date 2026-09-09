## Context

See `proposal.md` - Why. Current implementation, exact locations:

- `qc.set`/`qc.setHeader` sandbox bindings (`cli/api_runner.py:176-178` Python, `:217-218` JS) write into an in-memory `_output.state` dict inside the sandboxed subprocess, serialized back and merged into the run's `state["qaclan_vars"]` (`cli/api_runner.py:892-894` post-script, `:755` pre-script).
- `resolve_and_run_api_item()` unconditionally persists `state_updates` to the DB via `CollectionVarsRepo.upsert(collection_id, key, value)` (`web/api/services/runner_service.py:194-198`), which writes into `collection_vars.initial_value` (`web/api/repositories/collection_vars_repo.py:23-60`) — the same column the manual var-picker UI uses for the static default. There is no env dimension anywhere in this path.
- `resolve_vars()` (`cli/api_runner.py:57-72`) checks `state["qaclan_vars"]` before `env_vars` — this precedence is correct and stays as-is (see `api-environment-selection` spec, "Run-time variable precedence favors the collection's current value").
- The seed for `qaclan_vars` on every run comes from `CollectionVarsRepo.as_seed_dict(collection_id)` (`collection_vars_repo.py:71-79`, called from `runner_service.py:246,338,474,541`) — keyed only by `collection_id`, with no dependency on the active environment.
- Active environment per collection is `api_collections.env_name` (`cli/db.py:317`), a name string, read via `CollectionRepo.get()`.

The bug: because persistence and seeding are both env-agnostic, a `qc.set` value outlives environment switches and clobbers the static default.

## Goals / Non-Goals

**Goals:**
- Make a script-captured collection variable value apply only while the environment it was captured under is still the collection's bound environment.
- Preserve the user's manually configured static default independent of what scripts write.
- Keep existing run-time precedence (collection/runtime value beats env value) and existing script API (`qc.set` signature/behavior) unchanged — this is a storage/seeding fix, not an API change.

**Non-Goals:**
- No multi-environment "history" of captured values beyond the single most recent capture per environment binding is not required — one `runtime_value`/`runtime_env_name` pair per collection variable is enough to fix the bug (see Decisions).
- Not building a general 4-tier variable scoping system (global/collection/environment/local); this stays within the existing two-tier collection-vars + env-vars model, per the "Known gaps" note already in `docs/api-script-reference.md`.
- Not migrating/cleaning existing `collection_vars.initial_value` rows already polluted by the old bug (see Risks).

## Decisions

**One runtime slot per variable, not a per-environment history.** `collection_vars` gains `runtime_value` and `runtime_env_name` columns (nullable) rather than a separate table keyed by `(collection_id, key, env_name)`. Rationale: a collection has exactly one bound environment at a time, so only the capture made under the *currently* bound environment can ever be relevant; storing a full history per environment adds schema/query complexity (a join/lookup instead of a row read) with no behavioral benefit, since a capture under a since-abandoned environment binding is simply stale and should fall back to the static default anyway, not be resurrected later. Alternative considered: a `collection_var_runtime` table keyed by `(collection_id, key, env_name)` to preserve per-environment history (e.g. so switching back to "dev" restores the last "dev"-captured token without rerunning `/login`) — rejected as unnecessary scope beyond what the bug report asks for, and it reintroduces a subtler staleness problem (an old "dev" token could silently reappear when switching back).

**Write path split, not a flag on the existing `upsert()`.** New `upsert_runtime(collection_id, key, value, env_name)` method, separate from the existing `upsert()` used by the manual var-editor UI. Rationale: keeps the "who's allowed to touch `initial_value`" boundary explicit at the call-site/method level rather than a boolean parameter that both callers must remember to set correctly.

**Fallback is the static default, not an error or blank-with-warning.** When the runtime override doesn't match the active environment, `as_seed_dict()` returns the static `initial_value` for that key (or omits the key if no static default exists), so `resolve_vars()`'s existing "empty + warn" behavior for a genuinely undefined key is unaffected.

**No change to `resolve_vars()` precedence.** The fix is entirely in what `as_seed_dict()` returns; `qaclan_vars` still beats `env_vars` once seeded. This keeps the change minimal and avoids touching the well-tested-by-usage core resolution path shared by every request field (URL, headers, params, body, auth, path params).

## Risks / Trade-offs

[Existing `collection_vars.initial_value` rows already clobbered by the old bug, before this fix ships] → No automatic remediation; documented in proposal as accepted (no reliable way to distinguish script-polluted rows from genuinely user-set ones). Users affected can manually reset the value from the var-picker UI once the new UI distinguishes runtime vs. static.

[Losing the "last known good token per environment" convenience if a user frequently switches between two environments and doesn't want to rerun `/login` each time] → Accepted per the "one runtime slot" decision above; this is the correct behavior per the bug report (stale cross-environment values must not apply), and rerunning a login/setup script when switching environments is the expected, safe behavior.

[UI change scope not fully pinned down — exact var-picker component file wasn't identified during investigation] → tasks.md includes a task to locate the component before implementing the indicator; worst case this ships as a small follow-up if the UI surface is larger than expected, without blocking the data-layer fix which is the core of the bug.

## Migration Plan

- Additive schema migration only (two new nullable columns) — no data migration, no downtime, follows the existing pattern (`cli/db.py:324-334`).
- Rollback: revert the runner-service and repo changes; the additive columns can remain unused harmlessly, or be dropped in a follow-up migration if desired.
