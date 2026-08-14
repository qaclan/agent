## Context

See `proposal.md` — Why. Cloud sync is best-effort REST against qaclan.com; the client is `cli/api.py` (thin HTTP), `cli/sync.py` (push), and `cli/commands/pull.py` (pull merge). Negative-testing already pushes and pulls through the workspace path. The one leak is the *second* pull path.

There are, in fact, several pull endpoints — the user's assumption that pull is only `/api/pull/workspace` is not accurate:

- `GET /api/pull/workspace` — projects/features/scripts/collections/requests/env. Already carries all negative config (`pull_workspace`, `cli/commands/pull.py`).
- `GET /api/pull/api-runs` + `GET /api/pull/api-runs/<id>` — standalone collection-run history, pulled lazily when the API Runs view opens (`pull_api_run_history`). **This is where `negative_result` leaks.**
- `GET /api/pull/api-docs` — server-computed docs cache. Not negative-related.

`sync_api_collection_run_to_cloud` (`cli/sync.py:427`) already pushes `negative_result` (and `schema_drift`) on each `request_results` entry. `pull_api_run_detail` returns those results. But `pull_api_run_history` (`cli/commands/pull.py:414`) inserts `api_request_results` with a fixed column list that omits both `negative_result` and `schema_drift`, so the verdict is dropped on merge. Columns already exist locally (`cli/db.py` migrations `_migrate_api_negative` / `_migrate_api_schema_check` add them to `api_request_results`).

## Goals / Non-Goals

**Goals:**
- Make `pull_api_run_history` persist `negative_result` (and the same-line `schema_drift`) into `api_request_results`.
- Keep the fix null-safe: a result with no verdict pulls cleanly, storing an empty/None value.

**Non-Goals:**
- No push-side change (`cli/sync.py` already complete).
- No `pull_workspace` change (already carries negative config).
- No new DB columns, no server-side (qaclan.com) change.
- Not adding negative aggregates to run-header tables — `negative_result` lives only on `api_request_results` / `api_runs`, never on `api_collection_runs`.

## Decisions

**Decision 1: Fix only the run-history INSERT; leave push and workspace-pull untouched.**
They already round-trip the fields correctly (verified: `sync.py` sends collection default, request config, and per-result verdicts; `pull_workspace` reads collection default + request config). Widening scope would rewrite working code. Alternative — a broad "audit every sync call" pass — rejected as unnecessary churn; the leak is a single, identified INSERT.

**Decision 2: Fix `schema_drift` in the same edit even though it belongs to the schema-check feature.**
It rides the same push payload and is dropped on the exact same INSERT line. Fixing one and leaving the other produces a half-populated row and invites a second near-identical change. Rationale over alternatives: doing both is one line of column list + one JSON decode each, with no added risk. This is called out so it is a deliberate rider, not scope creep.

**Decision 3: JSON-decode on read, mirroring the workspace path.**
`negative_result`/`schema_drift` are stored as JSON text. Follow the existing pattern used elsewhere in the pull merge: `json.dumps(r["x"]) if r.get("x") else None` when writing to the column, so a missing verdict becomes `NULL` and a present one is preserved verbatim. No new serialization helper.

## Risks / Trade-offs

- [Server omits the field for old runs] → Guarded by `r.get("negative_result")` — a missing key stores `NULL`, the same as a run that never executed negatives. No pull failure.
- [Doc drift] → CLAUDE.md maintenance rule requires `docs/api-negative-testing-reference.md` to reflect any `cli/commands/pull.py` change in negative scope; updating it is a task, not optional.
- [Historical rows already pulled without the verdict] → Not back-filled. `api_collection_runs` are immutable once finished and `pull_api_run_history` skips runs it already has, so previously-pulled runs keep their null verdict. Acceptable: verdicts are re-pushed on the next run, and this is history, not live config.

## Migration Plan

Pure client code change; no schema migration (columns already present). Ships in the CLI/agent binary. Rollback is reverting the `pull.py` edit — older clients simply resume dropping the field, exactly today's behavior.
