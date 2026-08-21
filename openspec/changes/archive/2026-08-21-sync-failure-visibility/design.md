## Context

See proposal.md - Why. Relevant current-state facts that shape the approach:

- `sync_queue` (cli/db.py `_migrate_sync_queue`) already has `attempts`, `last_error`, `last_attempt_at` columns, populated by `drain_once()` (cli/sync_queue.py) on every failed dispatch. No schema change needed - the data already exists, it's just never read back out.
- `_dispatch()` (cli/sync_queue.py) handles 14 entity types via a per-type branch, each doing its own local `SELECT` to fetch the row needed to call the matching `cli/sync.py` function. Several of those (`feature`, `suite`, `api_collection`, `environment`, `suite_items` via its suite) transitively call `_ensure_project_synced()` (cli/sync.py), which re-attempts the parent project's sync from scratch on every call when the project has no `cloud_id` yet.
- `script` sync does *not* hard-depend on the project being synced first - it attaches `project_id`/`suite_id`/`feature_id` to the payload only if those parents already have a `cloud_id`, otherwise omits them and still syncs. So the cascade-failure problem is specific to entity types that call `_ensure_project_synced`/`_ensure_suite_synced`.
- `strict_mode()` (cli/sync.py) is active for the whole `_dispatch()` call, so a real HTTP failure inside `_ensure_project_synced` already propagates up as an exception and gets recorded as that row's `last_error` - it is not silently swallowed. The gap is purely visibility (nothing surfaces `last_error`) and redundant work (every dependent re-attempts the same doomed parent call).

## Goals / Non-Goals

**Goals:**
- Make failing sync-queue entries visible via the existing status/push endpoints and the push toast, using data already recorded.
- Stop a dependent entity from re-issuing an HTTP call for a parent (specifically: project) that just failed, within a short cooldown.

**Non-Goals:**
- Multi-level parent chains beyond entity→project (e.g. nested api_folder→api_folder→collection, or suite_items→suite→project two hops deep) - only the direct project dependency is guarded in this change. Deeper chains keep today's behavior (repeat attempts).
- Per-item exponential backoff / eventual give-up on a permanently-broken row - out of scope (this is the separate "Priority 3" idea from the investigation, not part of this change).
- Any change to `cli/api.py` timeout behavior - already fixed separately (`DEFAULT_TIMEOUT` added).

## Decisions

**1. New `list_failing()` helper in `cli/sync_queue.py`, shared by both endpoints.**
Single query: `SELECT entity_type, entity_id, op, attempts, last_error, last_attempt_at FROM sync_queue WHERE attempts > 0 ORDER BY attempts DESC, last_attempt_at DESC LIMIT 20`. Reuses the existing `idx_sync_queue_attempts` index. Capped at 20 to bound response size and avoid a status/push call turning into a large payload if hundreds of items are stuck. Each row is enriched with a human-readable label by looking up the entity's `name` in its local table (small `entity_type -> (table, name_column)` map, mirroring the per-type branches already in `_dispatch`); if the local row no longer exists (deleted after being queued), fall back to `f"{entity_type} {entity_id}"`.
Alternative considered: build the failing list ad hoc in `web/routes/sync.py` directly against the DB. Rejected - `cli/sync_queue.py` already owns all `sync_queue` table access; splitting that would duplicate the entity_type→table mapping that `_dispatch` already has.

**2. `sync_status()` and `push_now()` (web/routes/sync.py) both call `list_failing()` and include it as a `failing` array in their JSON.**
`push_now()` already computes `remaining` after `flush_sync()` - `failing` is added alongside it, not instead of it, so existing consumers of `remaining`/`queued` are unaffected (additive field).

**3. Parent-cooldown short-circuit scoped to the project level only, via a new `_recent_project_failure(project_id)` check in `cli/sync_queue.py`.**
Before `_dispatch()` calls a branch that would trigger `_ensure_project_synced` (feature, suite, api_collection, environment, suite_items-via-suite), check whether `sync_queue` already has a `project` row for that `project_id` with `attempts > 0` and `last_attempt_at` within `PARENT_FAILURE_COOLDOWN_SECONDS` (new constant, 60s - long enough to skip the next 1-2 drain cycles at `IDLE_SLEEP=30s`, short enough that a since-fixed project retries quickly). If so, skip the dependent's own dispatch, write `last_error = f"blocked on parent project: {project_last_error}"`, bump its `attempts`, and return without calling `_ensure_project_synced` at all.
Alternative considered: make `_ensure_project_synced` itself cooldown-aware (cache the failure in-process). Rejected - the queue table is already the source of truth shared across the worker thread and any request-thread `flush_sync()` call (see `_drain_lock` docstring for why cross-thread state already lives there); adding a second in-memory cache risks the two disagreeing.
Alternative considered: guard all transitive parent types (suite→project, api_folder→collection→project, etc). Rejected for this change - project is the single dependency every affected type shares, and it's the scenario from the actual bug report (one broken project stalls its whole tree). Deeper-chain guards are a natural follow-up once this pattern proves out, not required to fix the reported problem.

**4. UI: `triggerPush()` (web/static/app.js) branches on `res.failing?.length` instead of only `res.remaining`.**
When `failing` is non-empty: error-styled toast naming the first failing entity + its error (and a "+N more" suffix if more than one). When `remaining > 0` but `failing` is empty (items simply not yet attempted): keep today's neutral "will retry in background" toast.

## Risks / Trade-offs

- [Extra query per status/push call] → Bounded by `LIMIT 20` and the existing `attempts` index; negligible cost, same table already read for `queue_depth()`.
- [Cooldown check reads a project row that another thread is mid-retrying] → Worst case: one dependent skips a dispatch it could have attempted (e.g. project just succeeded microseconds earlier, cloud_id not yet visible to this read). Not a correctness issue - the dependent stays queued and gets picked up next cycle once the cooldown window passes or the project's `cloud_id` is set (whichever a normal `_ensure_project_synced` call would've found anyway).
- [Only project-level guard, not full chain] → A broken *suite* (rather than project) still lets its own dependents (suite_items) hammer it every cycle. Accepted per Non-Goals; narrower fix matches the reported failure mode exactly.

## Open Questions

(none - cooldown duration and guard scope are decided above)
