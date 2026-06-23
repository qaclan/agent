# 22 - Comments on Runs

Deep-dive on feature #22 from [feature-ideas.md](../feature-ideas.md). Covers what makes run comments different from a generic chat tool, when teams actually need them, and how they integrate with cloud sync.

---

## The problem

A test run fails. The QA engineer looks at it and recognizes it as a known flaky condition or a previously triaged issue. She re-runs it, it passes. She moves on.

Tomorrow a developer looks at the run history, sees the failure, and opens a ticket. 30 minutes wasted triaging something already known.

Or: a run fails, QA leaves for the day. Developer sees it the next morning. No context. Was this investigated? Is it blocking? Is it a real bug or infrastructure noise?

Run comments are async triage. They attach institutional knowledge directly to the data.

## Example

```
Run: checkout-flow — FAILED (Tuesday 14 Jan 15:32)

Comments:

  [Maria, QA]  Tue 15:35
  This is the modal-behind-pay-btn issue. Tracked in ABC-442.
  Not a blocker. Rerun passes. Marking as known flake.
  
  [Dev Bot]  Tue 15:35
  🔗 Linked to Jira: ABC-442

  [Tom, Dev]  Wed 09:02
  Fix deployed in commit a7f3e9b. Let's watch the next 5 runs.
  @Maria can you verify?

  [Maria, QA]  Wed 09:15
  Verified. 5 passes in a row. Closing.
```

No separate Slack thread needed. The knowledge lives next to the run data forever.

## Impact

| Dimension | Effect |
|---|---|
| Triage efficiency | "Was this investigated?" answered by looking at the run. Not by pinging teammates. |
| Institutional memory | Known issues, temporary workarounds, follow-up owners recorded permanently. |
| Async team coordination | QA and dev can work different hours and still communicate about the same run. |
| Solo developers | Less obvious value — can still add personal notes ("flaky, investigate after v2 release"). |

Overall: **medium impact** for solo users, **high impact** for teams of 2+. Very low implementation cost — mostly a CRUD table + UI.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **Cypress Cloud** | Run comments on specific test results. Paid. | Cloud-only. |
| **Mabl** | Comment on results, link to issues. Paid. | Cloud-only. |
| **GitHub PR reviews** | Inline comments on code. | Not on test results. Different context. |
| **Slack threads** | Async discussion. | Disconnected from run data. Knowledge lost when thread scrolls. |

**Our diff:** Comments attached to run data in QAClan's own DB. Visible in the same UI where the run lives. Cloud sync makes them visible to teammates. No external tool needed.

## Schema

```sql
CREATE TABLE run_comments (
    id            TEXT PRIMARY KEY,
    suite_run_id  TEXT REFERENCES suite_runs(id) ON DELETE CASCADE,
    script_run_id TEXT REFERENCES script_runs(id) ON DELETE CASCADE,
    -- One of suite_run_id or script_run_id is set. Not both.
    step_index    INTEGER,  -- NULL = comment on the whole run, not a specific step
    author        TEXT NOT NULL,   -- display name from config
    text          TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    updated_at    TEXT
);
```

## Author identity

QAClan does not have a user login system for local use. For local comments:
- Author = configured display name from `~/.qaclan/config.json` (`display_name` field, defaults to system hostname or "Local User").
- UI: first-time commenter prompted to set their name. Stored in config.

For cloud-synced comments:
- Author = authenticated qaclan.com account name.
- Cloud comments from teammates appear with their account names.

## Comment UI

**Suite run detail page:**
- Comment section at the bottom of the page.
- Chronological thread.
- Text input with Submit button.
- Each comment: avatar/initial, author name, timestamp, text. Edit and delete own comments only.

**Script run detail page:**
- Same thread for the specific script run.
- Optional: attach comment to a specific step ("Comment on step 9"). Shows step index as a thread anchor.

**@mention:**
- v1: plain text @Name. No notification integration.
- v2: @mention triggers notification via feature #19 (Notifier) if the mentioned user has notifications configured.

## Cloud sync

Run comments sync via existing `cli/sync.py` mechanism. Same pattern as other tables — add `cloud_id` column and include in sync payload.

For team visibility:
- Comment created locally → syncs to cloud → teammates' QAClan instances pull it on next sync.
- Cloud comments from teammates → synced to local DB → appear in local UI.

Sync frequency: comments are low-urgency. Sync on same schedule as other data (or on-demand via "Refresh" button).

## Implementation path

### Phase 1 — local comment thread on suite runs

- Add `run_comments` table migration.
- `GET /api/suite-runs/:id/comments` — returns comment thread.
- `POST /api/suite-runs/:id/comments` — add comment.
- `DELETE /api/run-comments/:id` — delete own comment.
- UI: comment thread on suite run detail page. Author = config display_name.

### Phase 2 — script-level and step-level comments

- Add script_run_id and step_index support to the same table.
- UI: "Comment on this step" link on each step row in script run detail.

### Phase 3 — @mention + notification

- Parse @Name in comment text.
- Look up notification config for the mentioned name.
- Send notification via feature #19 webhook/email.

### Phase 4 — cloud sync

- Add `cloud_id` to `run_comments`.
- Include in sync payload in [cli/sync.py](../../cli/sync.py).
- Merge strategy: last-write-wins per comment (edits), append-only for new comments.

## Open questions

- **Comment editing.** Allow editing after posting? Yes, with `updated_at` timestamp shown. Brief window (e.g. 5 minutes) or always? Always — async context, users need to correct mistakes hours later.
- **Rich text vs plain text.** Markdown? v1: plain text. v2: minimal Markdown (bold, links, code spans). Full rich text is overkill for run comments.
- **Delete vs soft-delete.** Hard delete loses the comment from history. Soft-delete (`deleted_at` column) preserves the record but shows "comment deleted". Soft-delete preferred for team audit trail. v1: hard delete is simpler.
- **Comment count badge.** Show comment count on run list view to indicate "this run has been discussed". Low-effort addition once comments exist.

## Next concrete step

Add `run_comments` table migration to [cli/db.py](../../cli/db.py). Add three routes (GET, POST, DELETE). Add comment thread component to suite run detail page. Hardest part is the UI, not the data layer. Ship Phase 1 (local only) before touching cloud sync.
