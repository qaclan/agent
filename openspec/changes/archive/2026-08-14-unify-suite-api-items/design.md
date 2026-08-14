## Context

See proposal.md - Why/Impact for motivation and file list. Key existing facts this design builds on (confirmed by code, not assumed):

- `suite_items` already has `item_type`/`script_id`/`api_request_id` (`cli/db.py:414-510`) — no schema change needed.
- `execute_run` (`web/routes/runs.py:230`) already branches per `item_type` and already calls `run_api_request()` for API items (`~422-511`), but calls it raw — never loads the parent `api_collections` row, never calls `_resolve_auth`/`_resolve_schema_check`/`_resolve_negative_check` (`web/api/services/runner_service.py:31-59`), and never persists extracted vars into `collection_vars`, all of which the standalone collection-run path (`RunnerService._execute_collection`/`run_collection`) already does per request.
- The suite editor (`web/static/app.js:3954-4089`) renders a legacy script-only "Scripts" section (drag-reorderable, posts to `PUT /suites/<id>/order` with `script_ids` only) and a separate "Items" section (all items, not reorderable).
- `state.json` under the run dir is the one shared file used both as Playwright's `storage_state` target (`cookies`/`origins`) and as the API side's `qaclan_vars` bucket (`web/routes/runs.py:350,451-470`). Each script strategy's teardown calls `context.storage_state(path=_STATE)`, which overwrites the whole file rather than merging.
- `collection-run-view.js` already renders an expandable per-request detail panel (status, headers, body, assertions, schema-drift pill, negative pill) for each request in a collection run — this is the pattern to extend to suites, not a new one to invent.
- `ApiRunRepo.list_by_suite_run(suite_run_id)` (`web/api/repositories/api_run_repo.py:44-53`) already exists and already returns everything an API item's detail view needs (joined with `api_requests` for name/method/url; `status`, `status_code`, `response_body`, `response_headers`, `assertion_results`, `schema_drift`, `duration_ms`, `error_message`). It's simply never called by the two historical read paths below.
- `GET /api/runs/<id>` (`get_run`, `web/routes/runs.py:145-189`) and `cli/report.py::generate_html_report` (`:146-227`) both query `script_runs` only — neither touches `api_runs`. Header stats (total/passed/failed/skipped) come from `suite_runs` columns and already count API items correctly, so reopening a past run or downloading its report shows a total that doesn't match the rows actually rendered — API items vanish entirely from both surfaces, not just their detail. Only the in-memory response built fresh right after `execute_run` finishes (`runs.py:794-808`) includes API rows, because that list is assembled during execution, not read back from either of these two paths.

## Goals / Non-Goals

**Goals:**
- One reorderable item list in the suite editor; no duplicate script rendering.
- Bulk, collection-grouped API request picker replacing the single-select dropdown.
- Suite-run API items get the same auth and schema-check resolution as a standalone collection run, by calling one function shared with the collection-run path rather than duplicating its logic.
- Suite-run API items persist extracted variables into `collection_vars`, matching collection-run behavior, and mirror the same values into the run's own `state.json` so a script item later in the same run can read them.
- `qaclan_vars` survives a script running between two API items.
- A suite API item's failure (assertion fail, request error, breaking schema drift) is treated the same as a script item's failure for stop-on-fail purposes.
- Suite run results let a user expand an API item to see its full response detail (status, headers, body, assertions, schema-drift verdict), reusing the collection-run view's existing rendering, backed by that suite run's own persisted result.
- Reopening a past suite run (Runs history) and downloading its HTML report both include API items alongside script items, matching the header totals — not just the live "just ran" view.

**Non-Goals:**
- **Negative testing never runs in a suite, under any configuration.** Not resolved, not fired, not displayed. It stays exclusively a collection-section concern. This is a deliberate scope boundary, not an oversight — negative testing is a fuzz/security probe with a very different cost and purpose than flow validation.
- No live-polling/async suite run view (`collection-run-view.js`'s polling model). Suite runs stay one synchronous request/response; only the result *payload* gets richer, not the run's execution/transport model. The expand-in-place detail is a client-side reveal of data already returned in that one response, not a new fetch.
- No suite-level override of a request's auth/schema-check/negative-check configuration. A suite always runs whatever the request/collection already has configured; changing that configuration still means going to the API section.
- No 4-tier variable scoping. Out of scope per `docs/api-script-reference.md`'s documented known gap; unrelated to this change.
- No change to how standalone collection runs behave — the shared function extraction is a refactor for the collection-run path (same behavior, moved code), not a behavior change for it.

## Decisions

**1. Extract one shared per-request execution function; both collection runs and suite runs call it.**
Today `_execute_collection`/`run_collection` (`web/api/services/runner_service.py`) inline the sequence: resolve auth → resolve schema-check → resolve negative-check → call `run_api_request` → persist `state_updates` into `collection_vars` via `CollectionVarsRepo`. Extract that sequence into one function, e.g. `resolve_and_run_api_item(req_row, collection_row, env_vars, state, state_path=None, include_negatives=True)`, returning the full result dict. `_execute_collection`/`run_collection` call it with `include_negatives=True` (unchanged behavior for them — pure refactor). The suite path (`execute_run`'s API-item branch) calls the same function with `include_negatives=False`, then additionally merges the returned `state_updates` into its own `state.json.qaclan_vars` for the script-item bridge.
This replaces the earlier idea of the suite path calling the three resolution helpers directly and skipping persistence — that would have left two divergent implementations of "run one API request" in the codebase, guaranteed to drift again. One function, two callers, is the standard fix.
Alternative considered: suite path keeps using `run_api_request` directly with hand-copied resolution calls, no `collection_vars` persistence. Rejected — this was the original design; discussion surfaced that it invents a second, ephemeral-only variable-persistence rule that contradicts how the rest of the app already treats automated runs (collection runs already persist), for no compensating benefit.

**2. Suite-run API items persist extracted vars into `collection_vars`, same as collection runs.**
Falls out of Decision 1 for free (the shared function always persists). Known trade-off: this makes running a suite have a visible side effect on the collection's shared variable store — a value extracted by a suite run can be seen by a teammate's next ad hoc send, and a suite run against one environment can overwrite a value another environment's run or manual test was relying on. This trade-off already exists today for collection runs; suites inheriting it is consistent, not a new risk class introduced by this change.
Alongside `collection_vars` persistence, the suite path also merges `state_updates` into the run's own `state.json.qaclan_vars`, because that is the only channel a same-run script item can read from (`QACLAN_STATE_<KEY>` env vars come from `state.json`, not from a `collection_vars` DB lookup a script subprocess has no access to). Not a duplicate mechanism — one extraction event, two consumers with genuinely different scopes (durable collection store vs. this-run script bridge).

**3. Negative testing is excluded from the suite path entirely — not resolved, not run, not shown.**
`resolve_and_run_api_item` is called with `include_negatives=False` from the suite path, so `_resolve_negative_check` is never invoked and `run_api_request` never receives negative cases to execute. This is a hard exclusion, not a default that could be toggled per suite later without further design — doing so would require deciding how negative sub-results roll up into stop-on-fail and suite run duration budgeting, neither of which this change addresses.

**4. Fix `state.json` merge at the write site, not by splitting into two files.**
Alternative considered: give API state its own file, separate from Playwright's `storage_state` target. Rejected — would require touching every script strategy's env var wiring and the suite-run state-loading code for no behavioral gain. The simpler, correct-at-the-source fix: before each strategy's `context.storage_state(path=_STATE)` call, read the existing file's `qaclan_vars` (if any) and write it back merged with Playwright's new `cookies`/`origins`, instead of letting Playwright's write be the last word. Concretely: replace `context.storage_state(path=_STATE)` with `state = context.storage_state(); merge qaclan_vars from existing file; write merged JSON` across the four strategy files listed in proposal.md Impact.

**5. Suite API item failure = assertion fail, request error, or breaking schema-drift.**
Chosen to match the severity model the API section already uses (breaking schema drift is already treated as the "fail" tier there, additive as "notify"). Negative-testing verdicts never factor in, since negatives never run in a suite (Decision 3). This failure definition feeds the suite's existing stop-on-fail skip logic identically to how a script item's failure does today — no new stop-on-fail mechanism, just a new condition that can trigger the existing one.

**6. Single generic reorder contract for mixed items.**
Replace `PUT /suites/<id>/order { script_ids }` with a version accepting an ordered list of `{item_id}` (the `suite_items.id`, not `script_id`/`api_request_id`) covering every item in the suite. This is the natural key since it already uniquely identifies a row regardless of type, and the frontend already has `item_id` available from the `/suites/<id>` GET response. **BREAKING** for the old contract, but it has exactly one caller (the suite editor being replaced in this same change), so no external compatibility concern.

**7. API picker: single modal, collection-grouped checkboxes, no collection-scope restriction.**
Allow selecting across collections in one picker session. Real suites commonly combine a shared "Auth"/"Core" collection with per-feature collections (e.g., login from one collection, business endpoints from another), so scoping the picker to one collection at a time would block a normal use case for no safety benefit (each request is still added as its own independent `suite_items` row either way). Collection grouping + search keeps the list navigable without a scope restriction.

**8. Suite run results: expand-in-place, reusing the collection-run view's rendering, backed by the suite's own persisted result.**
Each suite API item's row gets an expand control that reveals status, headers, body, assertions, and schema-drift verdict (no negative section — never produced) using the same rendering `collection-run-view.js` already has for its per-request detail. The data source is the suite run's own persisted per-item result (`api_runs` via `ApiRunRepo`), not the API section's live editor state — those are different datasets (this run's captured result vs. whatever's currently loaded in an open editor tab), so this is not "embed the request editor," it's a second consumer of an existing read-only renderer against a different, already-correct data source.

**9. Fix the two historical read paths by merging in `api_runs`, independently, without a shared helper.**
`get_run` adds one call to `ApiRunRepo().list_by_suite_run(run_id)`, normalizes each row into the same `item_type: 'api_request'` shape the live in-memory path already produces (`name` ← the repo's `request_name` alias), concatenates with the `script_runs` rows, and sorts the combined list by `order_index` before returning it — reconstructing exact suite order, since both tables' `order_index` values were written from the same `suite_items.order_index` at execution time. `generate_html_report` does the same merge, then branches its render loop between the existing `_render_script` and a new sibling `_render_api_item` (same plain-string-building style, same `<details><summary>...</summary><pre>...</pre></details>` collapsible pattern already used for a script's "Technical details").
Alternative considered: a single shared "load merged run items" helper used by both call sites. Rejected — the merge-and-sort itself is a few lines, and the two surfaces already diverge on the *script* side for good reason (`get_run` needs interactive fields like `screenshot_path`/`console_log` for the live modal; the report needs a fully self-contained static string) — forcing them through one shared loader would fight that existing divergence for negligible savings. Unlike Decision 1's execution-logic extraction, there's no real business logic here to keep in sync.

## Execution Flow

The suite run stays exactly one sequential pipeline — script and API items are not two separate lanes, and none of this design changes that. `execute_run` loops `suite_items` in `order_index` order, one item at a time, in one blocking HTTP request/response cycle. Each item type's full sub-flow:

1. Suite run starts: one request dir created, `state.json` initialized (empty, or carried from an earlier stage of the same run).
2. For each item in `order_index` order, block until it finishes before starting the next:
   - **Script item** (unchanged by this design): subprocess launch with `QACLAN_STATE_<KEY>` env vars from the current `state.json.qaclan_vars`, runs the Playwright script, teardown now merge-writes `state.json` (Decision 4) instead of overwriting it — cookies/origins update, `qaclan_vars` preserved.
   - **API item**: load the `api_requests` row and its parent `api_collections` row → call `resolve_and_run_api_item(..., include_negatives=False)` (Decision 1), which internally: resolves auth/schema-check → reads `state.json.qaclan_vars` + active environment vars → runs `pre_extractor`/`pre_script` (can `qc.set()`) → resolves `{{var}}` placeholders (`qaclan_vars` precedence over env vars, unchanged) → applies resolved auth → sends the HTTP request → runs `post_extractor`/`post_script` → evaluates assertions → if schema-check enabled, diffs against the frozen baseline and records a verdict → persists `state_updates` into `collection_vars` (Decision 2) → returns the full result → suite path merges the same `state_updates` into `state.json.qaclan_vars` (Decision 2) → determines pass/fail per Decision 5 → persists the result row (`ApiRunRepo`).
   - None of pre_script/post_script/pre_extractor/post_extractor/assertions are new or newly gated by this change — they already ran unconditionally for suite items today via `run_api_request`. This change adds auth/schema-check resolution and `collection_vars` persistence (both previously skipped), and explicitly keeps negative-check permanently off for this path.
3. Stop-on-fail: if an item is marked failed (script failure as today, or an API item per Decision 5) and the suite is configured to halt, remaining items are marked skipped instead of run — same mechanism as today, one more condition feeding it.
4. After the last item, the suite run finalizes (`suites.last_run_at`/`last_run_status`) and the full result set — every item's outcome, including any schema-drift verdicts and enough response detail to populate the expand-in-place view — returns in the one blocking response. The frontend renders it in one shot; expanding a row reveals data already present in that response, no additional fetch, no live polling.

## Risks / Trade-offs

[Suite runs now mutate `collection_vars`, a shared, durable store] → Accepted: matches existing collection-run behavior, not a new risk class. Documented in Decision 2 and worth calling out to users if support questions come up ("why did my collection variable change after a suite run") — no in-product warning planned for this change; revisit if it causes real confusion.

[Reordering contract is breaking] → Only one caller exists (the suite editor), replaced in the same change; no versioning needed.

[Shared execution function refactor touches the collection-run path's existing behavior surface] → Mitigated by keeping `include_negatives=True` as the collection-run call's default, so its observable behavior is unchanged; the refactor should be verified with the existing collection-run flow (auth/schema-check/negative-check, var persistence) before wiring the suite path to the same function.

[`storage_state` merge fix touches 4 strategy files] → Same mechanical change repeated per language; low risk since it's a narrowly-scoped read-merge-write around one existing call site per file, not new logic.

[Two separate historical surfaces (`get_run`, `generate_html_report`) both need the same `api_runs` merge] → Confirmed low risk: `ApiRunRepo.list_by_suite_run` already returns everything both surfaces need (`response_body`, `response_headers`, `assertion_results`, `schema_drift`, `status_code`, `duration_ms`, `error_message`) — no new storage or repo code required, only two small read-path patches (Decision 9).

## Migration Plan

No data migration — schema already supports mixed items and `collection_vars`/`api_runs` already exist. Rollout is a single code change (execution-function extraction + refactor, state-merge fix, frontend editor/picker/result-view rewrite) behind no feature flag, since it corrects existing broken behavior (auth silently not applied, vars not persisted) rather than introducing new opt-in behavior. Rollback is a plain revert if needed.
