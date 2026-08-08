## Why

Negative-testing config and verdicts already push to the cloud and pull back through `GET /api/pull/workspace`, but the workspace endpoint is not the only pull path. Standalone collection-run history comes down a **separate** path — `GET /api/pull/api-runs` + `GET /api/pull/api-runs/<id>` (`pull_api_run_history`) — and that path drops the per-result `negative_result` verdict when it inserts `api_request_results`. A teammate who pulls a collection run someone else executed sees the requests and pass/fail counts but loses every negative-testing verdict (including critical false-pass findings) attached to those results. The data was pushed correctly; the run-history pull silently discards it.

## What Changes

- Persist `negative_result` on `api_request_results` in `pull_api_run_history` (`cli/commands/pull.py`) so negative verdicts survive the collection-run history pull, matching what `sync_api_collection_run_to_cloud` already pushes.
- Close the identical same-INSERT gap for `schema_drift` (the response-schema-check verdict rides the same push payload and is dropped on the same line) — one fix, two verdict fields, no half-populated row.
- No changes to the push side or to `pull_workspace`: both already round-trip the negative-testing fields correctly (collection `negative_check_default`; request `negative_cases` / `negative_check` / `field_constraints`; per-result `negative_result`). This change captures that existing behavior as a written requirement and fixes the one leaking path.
- Update `docs/api-negative-testing-reference.md` per the CLAUDE.md maintenance rule (any `cli/commands/pull.py` change in negative scope must be reflected there).

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `api-negative-testing`: add a requirement that negative-testing configuration and verdicts survive a full cloud-sync round-trip across **all** sync paths — push, workspace pull, and collection-run-history pull — so no path silently drops the verdict.

## Impact

- Code: `cli/commands/pull.py` (`pull_api_run_history` — read `negative_result`/`schema_drift` from `pull_api_run_detail` results and add them to the `api_request_results` INSERT column list).
- No change to `cli/api.py` (transparent JSON pass-through — server already returns whatever was pushed) or `cli/sync.py` (push already complete).
- No new DB columns: `api_request_results.negative_result` and `.schema_drift` already exist (`cli/db.py` migrations).
- Server-side (qaclan.com) is out of scope — assumed to store and echo the fields the client already sends.
- Docs: `docs/api-negative-testing-reference.md` (maintenance-rule sync).
