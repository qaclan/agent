# 20 - Public Share Link

Deep-dive on feature #20 from [feature-ideas.md](../feature-ideas.md). Covers what "public" means for a local-first tool, how cloud sync gates this feature, and what the share token must and must not expose.

---

## The problem

QA finds a bug. Wants to share evidence with the developer.

**Current flow:**
1. QA opens QAClan run detail page.
2. Takes a screenshot of the browser window (meta-screenshot).
3. Pastes into Slack or Jira.
4. Dev gets a screenshot of a screenshot. No trace. No steps. No error detail. No reproduction steps.

Or:
1. QA exports something manually (zip? copy-paste?).
2. Dev installs QAClan, imports, looks at their local instance.

Both are terrible.

**With a share link:**
1. Click "Share Run".
2. Copy link. Paste into Jira comment.
3. Dev opens link in browser. Sees: exact steps, failure screenshot, error category, step timing, trace (if captured).

## Example

```
QA clicks "Share Run" on run detail page for "checkout-flow" FAILED.
QAClan shows: https://qaclan.com/r/7x3kP9mBqF

Dev opens link (no login required):
  Run: checkout-flow
  Suite: smoke | Environment: staging | Date: 2025-01-14 15:32

  Step 1    PASS  goto /cart           (234ms)
  Step 2    PASS  fill #qty            (89ms)
  Step 3    PASS  click Add to Cart    (312ms)
  ...
  Step 9    FAIL  click #pay-btn       Locator timeout (10000ms)
  
  Screenshot: [image of page with modal overlay visible]
  Error: Element not interactable. Selector '#pay-btn' matched 1 element 
         but it was covered by .promo-modal
  
  [View Trace] (if trace was captured)
```

## Impact

| Dimension | Effect |
|---|---|
| Bug reporting quality | Developers see the exact failure instead of a description or screenshot-of-screenshot. High. |
| Triage speed | "Reproduce this" becomes "open this link". Hours → minutes for first contact. |
| Non-QAClan users | Developers, product managers, clients see test results without installing QAClan. |
| Product virality | Every shared link exposes QAClan to a new user. Natural growth channel. |

Overall: **high marketing and collaboration impact.** Low on the priority list if the team is solo, but critical for any team with more than one person.

## Cloud dependency

Share links require a cloud endpoint. The run data must be accessible from outside the user's machine.

This feature is gated on:
1. **Cloud sync being active** — user must have an account and the run must have been synced.
2. **qaclan.com hosting the share view** — the `qaclan.com/r/<token>` page renders run data fetched from the cloud.

Users without cloud sync see: "Upgrade to enable share links" (or "Log in to share").

This is intentional. It is also a conversion lever: teams discover they need share links, which drives cloud account creation.

## What the share link exposes

**Included:**
- Run summary: suite, environment name, status, duration, date.
- Step list: action, locator, status, duration, error message.
- Failure screenshot.
- Error detail (structured category, title, next_step suggestion).
- Trace viewer link (if trace_path exists and trace was uploaded).

**Not included:**
- Raw console log (may contain PII or tokens).
- Network log (may contain auth headers, request bodies with credentials).
- Env var values (especially secrets).
- Script source code (opt-in only — some users have proprietary selectors).

User controls what's included when generating the link (checkboxes for each category).

## Token design

```
Token: 7x3kP9mBqF  (10-char base62 = 62^10 ≈ 839 trillion combinations)
URL:   https://qaclan.com/r/7x3kP9mBqF
```

Properties:
- Globally unique.
- No information about the run or user encoded in the token.
- Revocable: user can delete the token from QAClan settings → link 404s.
- Optional expiry: 7 days, 30 days, never.

## Schema

```sql
CREATE TABLE share_links (
    id          TEXT PRIMARY KEY,  -- the token
    run_id      TEXT NOT NULL,     -- suite_run_id or script_run_id
    run_type    TEXT NOT NULL,     -- 'suite_run' | 'script_run'
    include_mask TEXT NOT NULL,    -- JSON: {screenshots, trace, script_source}
    expires_at  TEXT,              -- NULL = never
    views       INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL
);
```

This table lives on the cloud side, not local. The local QAClan client POSTs to the cloud API to create a share link token.

## Implementation path

### Phase 1 — generate link + basic view

- Cloud API: `POST /api/share` (with auth) → creates share token, returns URL.
- Local client: "Share Run" button → POST to cloud → shows URL + copy button.
- Cloud view: `GET /r/<token>` → fetch run data associated with token → render read-only page.
- Run data synced to cloud via existing sync flow ([cli/sync.py](../../cli/sync.py)).

### Phase 2 — privacy controls

- UI: before generating link, show checkboxes: "Include screenshots", "Include trace", "Include script source".
- Store mask in `share_links.include_mask`. Cloud renderer respects mask.
- Default: screenshots yes, trace yes, script source no.

### Phase 3 — expiry + revocation

- Expiry picker: 7 days / 30 days / never.
- "Manage shared links" page in QAClan: list of active tokens with revoke buttons.
- Expired tokens: cloud returns 410 Gone with "This link has expired."

## Link for offline teams

Teams that cannot use cloud sync (air-gapped, private data) need an alternative:

**Option: static HTML export.** `qaclan run export <run_id> --format html --output report.html` generates a self-contained HTML file with embedded screenshots. User shares the file directly. No cloud needed.

This is a lower-priority v2 feature but important for enterprise/air-gapped use cases.

## Open questions

- **Sync latency.** If the run just finished, cloud sync may not have uploaded it yet. Share link generated before sync completes → link points to non-existent data. Options: (a) trigger immediate sync on "Share Run" click, (b) show "Syncing..." state while waiting, (c) queue the share link creation until sync confirms. Option (b) is best UX. Option (a) is simplest to implement.
- **Cloud storage cost.** Screenshots per run can be 1–5MB. With traces: 5–50MB per suite run. At scale, public share links could drive significant cloud storage cost. Add a storage tier to the cloud subscription model.
- **Link in notifications.** Feature #19 (notifications) includes a "View report" link. When share links are available, replace `http://localhost:7823/runs/...` with `https://qaclan.com/r/<token>` in notification messages. Requires generating a share link automatically when a scheduled run completes.

## Next concrete step

This feature requires cloud infrastructure changes on qaclan.com, not just local client changes. The local client side (`POST /api/share` button + schema) can be built ahead of the cloud side. Build the local "Share" button that POSTs to the cloud API endpoint (even if the endpoint returns 501 initially). Then implement the cloud side separately.
