# 04 - Snippet Library

Deep-dive on feature #4 from [feature-ideas.md](../feature-ideas.md). Covers scope model, parameterization, and how it differs from generic code snippet tools.

---

## The problem

QAClan users repeat the same boilerplate in every script: login sequence, cookie dismissal, waiting for hydration, navigating to a base URL. Right now that means:

1. Open an old script.
2. Find the relevant lines.
3. Copy them.
4. Paste into the new script.
5. Adjust hardcoded values.

No catalog. No reuse tracking. Break the login flow once and you update it in every script that copied it.

## Example

```python
# Without snippets: copied into 12 scripts, drift guaranteed.
await page.goto("/login")
await page.locator("#email").fill("admin@example.com")
await page.locator("#password").fill("hunter2")
await page.locator("text=Sign In").click()
await page.wait_for_url("/dashboard")

# With snippets: "login_as_admin" → prompts for {{email}} and {{password}} → inserts:
await page.goto("/login")
await page.locator("#email").fill("admin@example.com")    # substituted from prompt
await page.locator("#password").fill("MyRealPw!")         # substituted from prompt
await page.locator("text=Sign In").click()
await page.wait_for_url("/dashboard")

# Update the snippet once → all new insertions are correct.
# Already-inserted copies need manual update (warn user how many times snippet was used).
```

## Impact

| Dimension | Effect |
|---|---|
| Authoring speed | Insert a 20-line login flow in 2 clicks instead of 10 minutes of copy-paste. High. |
| Drift prevention | Fix a selector in one place. All future insertions pick it up. Existing copies still drift — but usage counter shows scope of the problem. |
| Onboarding | New team member gets working flows immediately, does not reverse-engineer the login sequence. |
| Script quality | Encourages extraction of messy flows (cookie banners, MFA) into named, documented snippets instead of buried boilerplate. |

Overall: **medium-high impact**. Not as dramatic as scheduling or notifications but reduces daily friction significantly. High usage frequency even for small teams.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **VS Code snippets** | Insert text at cursor, tab-stop placeholders. Generic. No Playwright awareness. | No catalog per project. No team sharing. No usage tracking. No language-aware Playwright code. |
| **Postman Collections** | Shared request library for HTTP calls. | HTTP only. Not E2E flows. |
| **Cypress custom commands** | `cy.login()` pattern — defines reusable commands in `cypress/support/commands.js`. | Requires understanding Cypress internals. No catalog UI. Only JS. |
| **Playwright fixtures** | `test.extend({login: async ({page}) => {...}})` — type-safe, composable. | Requires TypeScript knowledge and Playwright Test runner. Manual, no catalog. |
| **GitHub Copilot** | Suggests code. Sometimes repeats patterns it saw. | Not project-aware. No explicit catalog. No team sharing from QAClan context. |

**Our diff:** Snippets live in QAClan's DB scoped to the project or global. They know about QAClan's multi-language strategies (Python/JS/TS). They have named parameters that prompt on insert. They track usage count so users know how many scripts would be affected by an update. No IDE required.

## Schema

```sql
CREATE TABLE snippets (
    id          TEXT PRIMARY KEY,
    project_id  TEXT REFERENCES projects(id) ON DELETE CASCADE,
    -- NULL project_id = global snippet (all projects)
    name        TEXT NOT NULL,
    description TEXT,
    language    TEXT NOT NULL,  -- python | javascript | typescript
    code        TEXT NOT NULL,  -- may contain {{placeholder}} tokens
    tags        TEXT,           -- comma-separated, for filtering
    use_count   INTEGER DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
```

## Parameterization

Placeholders use `{{name}}` syntax. On insert:

1. Parser scans snippet code for `{{...}}` tokens.
2. UI shows a prompt dialog with one field per unique placeholder.
3. User fills values (or picks from env vars).
4. Insertion substitutes all occurrences.

Edge case: if user cancels the prompt, cancel insertion entirely. No partial insert.

## Implementation path

### Phase 1 — snippet CRUD + manual insert

- Add `snippets` table via migration in [cli/db.py](../../cli/db.py).
- REST routes: `GET/POST /api/snippets`, `PUT/DELETE /api/snippets/:id`.
- Snippet panel in script editor: search bar + list. Click to insert at cursor (no param support yet).
- Global snippets show with a globe icon; project snippets with a folder icon.

### Phase 2 — parameterization

- Parse `{{placeholder}}` on insert.
- Prompt dialog with one field per token.
- Env var selector: "use value from env var `BASE_URL`" shortcut.

### Phase 3 — usage tracking + update nudge

- Increment `use_count` on each insert.
- On snippet edit: show "Used in X scripts. Edits affect future insertions only. View scripts?"
- Link to a list of scripts that have previously used this snippet (requires an insert-event log, not just a counter).

### Phase 4 — team sync

- Snippets sync via existing cloud sync flow (`cli/sync.py`) — same pattern as scripts.
- Org-level snippets created from qaclan.com, pushed to all team members on next sync.

## Open questions

- **Language mismatch.** User picks a JS snippet while editing a Python script. Options: block it (hard fail), warn and allow, or translate (complex). Start with warn + allow. Translation requires LLM or a mapping layer.
- **Snippet versioning.** If snippet changes, old insertions are stale. Track which version was inserted? Or just usage count and let users audit manually? Start with count only.
- **Cursor position detection.** Web editor needs to know caret line/col to insert correctly. Monaco editor exposes this via `editor.getPosition()`. Verify with CodeMirror fallback.

## Next concrete step

Add `snippets` table migration to [cli/db.py](../../cli/db.py). Add `GET /api/snippets?project_id=` and `POST /api/snippets` routes. Wire a collapsible snippet panel into the script editor sidebar with search + click-to-insert (Phase 1 only). No params yet.
