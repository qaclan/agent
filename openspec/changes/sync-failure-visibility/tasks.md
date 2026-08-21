## 1. Sync-queue failing-list helper

- [x] 1.1 Add `list_failing(limit=20)` to `cli/sync_queue.py`: query `sync_queue WHERE attempts > 0 ORDER BY attempts DESC, last_attempt_at DESC LIMIT ?`, enrich each row with a human-readable label via a small `entity_type -> (table, name_column)` map, falling back to `f"{entity_type} {entity_id}"` when the local row no longer exists.
- [x] 1.2 Return `{entity_type, entity_id, label, attempts, last_error, last_attempt_at}` per row from `list_failing()`.

## 2. Parent-cooldown short-circuit

- [x] 2.1 Add `PARENT_FAILURE_COOLDOWN_SECONDS = 60` constant to `cli/sync_queue.py` alongside the existing `IDLE_SLEEP`/`OFFLINE_BACKOFFS`/`BATCH_SIZE` constants.
- [x] 2.2 Add `_recent_project_failure(conn, project_id)` to `cli/sync_queue.py`: look up the `project` row in `sync_queue` for that `project_id`, return its `last_error` if `attempts > 0` and `last_attempt_at` is within the cooldown window, else `None`.
- [x] 2.3 In `_dispatch()`, for the `feature`, `suite`, `api_collection`, `environment`, and `suite_items` branches (the ones whose sync path calls `_ensure_project_synced`/`_ensure_suite_synced`→project), call `_recent_project_failure()` first using that row's `project_id`; if it returns an error, raise an exception with message `f"blocked on parent project: {error}"` instead of calling the normal sync function, so `drain_once()`'s existing per-row except block records it as this row's `attempts`/`last_error` the same way any other failure is recorded.
- [x] 2.4 Verify `script` dispatch is left untouched (it doesn't hard-depend on project sync, per design.md Context).

## 3. Status and push endpoints

- [x] 3.1 `web/routes/sync.py::sync_status()`: call `list_failing()` and include it as `"failing": [...]` in the JSON response alongside `queue_depth`.
- [x] 3.2 `web/routes/sync.py::push_now()`: after computing `remaining`, call `list_failing()` and include `"failing": [...]` in the response whenever `remaining > 0` (empty list when `remaining == 0`).

## 4. UI toast

- [x] 4.1 `web/static/app.js::triggerPush()`: when `res.failing` is non-empty, show an error-styled toast naming the first failing entity's label + `last_error` (with a "+N more" suffix if `res.failing.length > 1`), instead of the current generic `res.message` toast.
- [x] 4.2 Keep the existing neutral "still pending, will retry in background" toast for the case where `res.remaining > 0` but `res.failing` is empty.

## 5. Verification

- [x] 5.1 Manually reproduce the cascade scenario (e.g. point a project's sync at a URL that 4xxs, or otherwise force `sync_project_to_cloud` to fail) and confirm: `GET /api/sync/status` lists the project as failing with its real error; a dependent feature/suite under it is marked `blocked on parent project: ...` rather than re-issuing its own HTTP call every drain cycle (check request count/logs); Push toast shows the error-styled notice.
      Verified via an isolated sandbox DB (not the real `~/.qaclan`): seeded a failing project + dependent feature, ran the real `drain_once()`/`list_failing()` code paths with `api.sync_project` stubbed to count calls. Confirmed the feature short-circuits with `last_error = "blocked on parent project: ..."` and contributes zero extra `api.sync_project` calls across two drain cycles (only the project's own natural retry calls it). `GET /api/sync/status` and `POST /api/sync/push` (via Flask test client) both return the `failing` array with the correct label/error. Frontend toast branch verified by code inspection (`res.failing.length > 0` path renders the error toast) - no browser available in this environment for a visual check.
- [x] 5.2 Confirm the ordinary case (items simply queued, not yet attempted) still shows the existing neutral "will retry in background" toast and `failing` is empty.
      Verified: a freshly-enqueued item (attempts=0) is absent from `list_failing()`, so the frontend takes the existing `res.remaining > 0` / `failing` empty branch unchanged.
- [x] 5.3 Confirm `script` entities under the same broken project still sync normally (per design.md, they don't require `_ensure_project_synced`).
      Verified: with the same project stuck failing, a queued script under it still called `api.sync_script` exactly once and synced successfully (removed from queue) - the project guard was never consulted for the script branch, as designed.
