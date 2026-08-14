## 1. Fix the run-history pull merge

- [x] 1.1 In `cli/commands/pull.py::pull_api_run_history`, add `negative_result` and `schema_drift` to the `api_request_results` INSERT column list and its placeholders.
- [x] 1.2 Read both from each `detail["request_results"]` entry with the pull's JSON pattern: `json.dumps(r["negative_result"]) if r.get("negative_result") else None` (same for `schema_drift`); a missing key stores `NULL`.
- [x] 1.3 Confirm no other required column in that INSERT was left unset by the edit (row values line up with the placeholders).

## 2. Verify the round-trip end-to-end

- [x] 2.1 Confirm the push side already sends these fields — `sync_api_collection_run_to_cloud` (`cli/sync.py`) includes `negative_result`/`schema_drift` per result (no change expected; verify only).
- [x] 2.2 Confirm `pull_workspace` already restores `negative_check_default`, `negative_cases`, `negative_check`, `field_constraints` (no change expected; verify only).
- [x] 2.3 Sanity-run: push a collection run that has a `negative_result`, pull its history on a fresh local DB, and confirm the stored `api_request_results.negative_result` matches; pull a run without negatives and confirm the merge succeeds with `NULL`.

## 3. Docs (maintenance rule)

- [x] 3.1 Update `docs/api-negative-testing-reference.md` to note that `negative_result` now round-trips through the collection-run-history pull path (`pull_api_run_history`), not only the workspace pull.

## 4. Close out

- [x] 4.1 Run `npx openspec validate sync-negative-verdicts-run-history --strict` and fix any reported issues.
