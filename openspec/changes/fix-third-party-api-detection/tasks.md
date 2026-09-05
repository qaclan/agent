## 1. Backend — surface start_url_value in run results

- [x] 1.1 In `web/routes/runs.py::execute_run`, add `"start_url_value": item["start_url_value"]` to the success-path `script_results.append(...)` block (~line 744).
- [x] 1.2 Add the same field to the timeout-path `script_results.append(...)` block (~line 796).
- [x] 1.3 Add the same field to the internal-error-path `script_results.append(...)` block (~line 830).
- [x] 1.4 Verify no other `script_results.append(...)` call sites for script items (as opposed to `api_request` items) were missed. (Confirmed: lines 422/555/578 are `api_request` items, out of scope; line 437 is the SKIPPED-script branch, which never has `captured_requests` and so needs no `start_url_value`.)

## 2. Frontend — carry start URL through to the review modal

- [x] 2.1 In `web/static/app.js::showRunResults`, tag each flattened captured request with `_scriptStartUrl: s.start_url_value` alongside the existing `_scriptName: s.name` (~line 4403).
- [x] 2.2 In `web/static/app.js::reviewRunCapturedRequests`, pass a per-request-aware start URL to `showRequestReviewModal` instead of the bare `requests[0].url` fallback (~line 4371) — keep `requests[0].url` only as the last-resort fallback when `_scriptStartUrl` is absent (e.g. a stale cached run response), per design.md's fail-open behavior.

## 3. Review modal — per-request classification

- [x] 3.1 In `web/static/api/views/request-review-modal.js`, replace the single hoisted `startRootDomain` (derived once from the `startUrl` param) with a per-row root domain computed from `r._scriptStartUrl` (falling back to the modal's `startUrl` param when a request has no `_scriptStartUrl`, so the existing Record-APIs and import flows keep working unchanged). Implemented as `_rowRootDomain(r)`.
- [x] 3.2 Update `thirdPartyCount` to count using each request's own reference domain instead of the shared `startRootDomain`.
- [x] 3.3 Update `_visible()`'s hide-third-party filter to use each request's own reference domain.
- [x] 3.4 Update the per-row `isThirdParty` flag (used for the origin badge styling) to use that same per-row reference domain.
- [x] 3.5 Confirm a request whose owning script has no start URL (and no fallback `startUrl`) is never flagged third-party and never counted in `thirdPartyCount` (per spec's "Missing start URL disables classification for that script's requests"). `_rowRootDomain` returns `''` in that case, which is falsy everywhere it gates classification (thirdPartyCount filter, isThirdParty, and `_visible()`'s `!rootDomain ||` keeps such rows visible even while hiding third-party).

## 4. Verification

No browser/E2E test harness exists in this repo (per CLAUDE.md: "no automated tests or linting configured") and this sandbox has no access to a live external test site or an interactive browser to drive real codegen/run/save-collection flows. Verified instead by extracting the exact classification algorithm now in `request-review-modal.js` (`_rootDomain`, `_rowRootDomain`) into a standalone script and running it against fixtures matching each scenario below — all 4 passed. This confirms the logic is correct; it does not exercise the real DOM rendering, the backend response shape end-to-end, or the actual save-as-collection UI. Recommend a real click-through pass (codegen against a site with an early-firing third-party call, plus a 2-script suite across two domains) before merging.

- [x] 4.1 Reproduce the original bug scenario logically: third-party request (`maps.googleapis.com`) captured before the script's own API (`crm-api.shikho.dev`, script start URL `crm.shikho.dev`) — confirmed own API classifies "main", third-party call classifies "third-party", independent of capture order. (Verified via algorithm-level fixture, not a live browser run — see note above.)
- [x] 4.2 Suite with two scripts on two different domains — confirmed each script's own API classifies "main" for that script, and the other script's domain is not flagged third-party. (Verified via algorithm-level fixture, not a live browser run.)
- [x] 4.3 Single-script Record-APIs flow (no `_scriptStartUrl` on the request, relies on the modal's `startUrl` param) — confirmed classification still works via the fallback path, matching pre-existing behavior. (Verified via algorithm-level fixture.)
- [x] 4.4 Script with no recorded start URL, mixed with a script that has one — confirmed the unclassified script's own requests are never flagged third-party, and the other script's classification is unaffected. (Verified via algorithm-level fixture.)
