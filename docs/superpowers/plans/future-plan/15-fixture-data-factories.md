# 15 - Fixture / Data Factories

Deep-dive on feature #15 from [feature-ideas.md](../feature-ideas.md). Covers the data lifecycle (create → use → clean up), integration patterns, and why hardcoded test data is a liability.

---

## The problem

Most QAClan test scripts today rely on hardcoded test data:

```python
# Hardcoded — fragile
await page.fill("#email", "admin@example.com")
await page.fill("#password", "hunter2")
```

Problems:
1. Admin account is shared across all runs. Parallel runs interfere.
2. Password changes → all scripts break.
3. Test creates a record (order, user, content) → record accumulates → staging DB grows → performance degrades.
4. No way to verify data-driven behavior (e.g. "admin sees X but member sees Y").

## Example

```python
# With factories:
user = await factory.create("user", role="member", email_prefix="test")
# Creates: { id: "usr_abc123", email: "test-8f3a@example.com", password: "Pw!8f3a" }

await page.goto("/login")
await page.fill("#email", user["email"])
await page.fill("#password", user["password"])
await page.click("text=Sign In")
await page.wait_for_url("/dashboard")

# After test: factory.cleanup() deletes usr_abc123 via API
```

Each run gets fresh, unique data. No shared state. No accumulation.

## Impact

| Dimension | Effect |
|---|---|
| Test isolation | Each run has its own data → parallel runs possible → connects to feature #7 (Parallel Run Groups). |
| Stability | No "test user account got deleted by another run" failures. High. |
| Data-driven coverage | Test member vs admin vs guest flows with the same script by swapping the factory role. |
| Cleanup | Staging DB stays clean. DevOps happy. |

Overall: **medium-high impact**. Critical for teams moving beyond a single developer using the same test account.

## How this differs from existing tools

| Tool | What it does | Gap |
|---|---|---|
| **FactoryBot (Rails)** | Ruby DSL: `FactoryBot.create(:user, role: :admin)`. Talks to DB directly. | Rails/ActiveRecord only. Cleans up via DB rollback (database transactions). Not applicable to E2E over HTTP. |
| **factory_boy (Python)** | Python factories, usually with Django ORM. | ORM-coupled. Does not go through the app's API. Does not create realistic session state. |
| **Cypress fixtures** | Static JSON files loaded as test data. | Static, not generated. No cleanup. No API creation. |
| **Playwright `test.extend`** | Composable fixtures for setup/teardown in Playwright Test. | Requires Playwright Test runner. TypeScript. No catalog. No QAClan integration. |
| **Faker.js / Faker (Python)** | Generate random fake data (names, emails, addresses). | Data generation only. No API call to create the record. No cleanup tracking. |

**Our diff:** QAClan factories live in the DB as reusable definitions. Each factory knows how to create a record via the app's API (not direct DB). Created records are tracked in a `factory_instances` table so cleanup is reliable even if the test script crashes. Multi-language: same factory called from Python or JS scripts.

## Architecture

### Factory definitions

Defined in QAClan UI (or YAML files), not hardcoded in scripts. A factory is:

```json
{
  "name": "user",
  "create_endpoint": "POST /api/users",
  "create_body": {
    "email": "{{email_prefix}}-{{random_hex_6}}@example.com",
    "password": "Pw!{{random_hex_6}}",
    "role": "{{role|member}}"
  },
  "id_path": "$.data.id",
  "delete_endpoint": "DELETE /api/users/{{id}}"
}
```

Fields:
- `create_endpoint` — HTTP method + path relative to project base URL.
- `create_body` — JSON body with template tokens.
- `id_path` — JSONPath to extract the created record's ID from the response.
- `delete_endpoint` — cleanup endpoint, uses the extracted ID.

### Template tokens

| Token | Result |
|---|---|
| `{{random_hex_6}}` | 6-char random hex like `8f3a2c` |
| `{{random_email}}` | `test-8f3a2c@qaclan-test.example.com` |
| `{{param_name\|default}}` | Script-supplied param, falls back to default |
| `{{timestamp}}` | Unix timestamp for uniqueness |

### Script-side API

The harness exposes a `factory` object via `QACLAN_FACTORY_SOCKET`:

```python
# Python harness
from qaclan_factory import factory

user = await factory.create("user", role="admin")
order = await factory.create("order", user_id=user["id"], items=3)
# factory.cleanup() called automatically at script teardown — or explicitly
```

The harness-side client sends a JSON message to a factory server (in QAClan web process), which makes the actual HTTP request and tracks the created instance.

## Schema

```sql
CREATE TABLE factory_definitions (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    create_endpoint TEXT NOT NULL,
    create_body TEXT NOT NULL,  -- JSON template
    id_path     TEXT NOT NULL,  -- JSONPath like $.data.id
    delete_endpoint TEXT,       -- NULL = no cleanup
    created_at  TEXT NOT NULL
);

CREATE TABLE factory_instances (
    id              TEXT PRIMARY KEY,
    definition_id   TEXT NOT NULL REFERENCES factory_definitions(id),
    script_run_id   TEXT REFERENCES script_runs(id) ON DELETE CASCADE,
    record_id       TEXT NOT NULL,  -- the created entity's ID
    deleted_at      TEXT,           -- NULL = not yet cleaned up
    created_at      TEXT NOT NULL
);
```

`factory_instances` enables:
- Cleanup retry if first attempt failed.
- Manual cleanup of orphaned records (script crashed before teardown).
- Audit of what data was created by which run.

## Implementation path

### Phase 1 — factory definitions CRUD

- Add `factory_definitions` and `factory_instances` tables.
- UI: "Factories" tab in project settings. Create/edit/delete factory definitions.
- Test factory: "Create one now" button — calls the endpoint, shows the raw response, verifies ID extraction.

### Phase 2 — factory client in Python harness

- Runner starts factory server (simple HTTP handler inside the QAClan process).
- Python harness: `qaclan_factory.py` module injected alongside the script.
- `factory.create(name, **params)` → POST to factory server → factory server calls app API → returns record data.
- On harness teardown: `factory.cleanup()` → factory server calls delete endpoints for all instances created in this run.

### Phase 3 — cleanup on crash

- `factory_instances` rows with `deleted_at = NULL` and `script_run_id` of a FAILED run → orphaned records.
- UI: "Orphaned factory instances" warning. "Clean up now" button sends delete requests.
- Optional: auto-cleanup on next run start for the same project.

### Phase 4 — JS/TS harness support

- Same factory server protocol, JS client module (`qaclan-factory.js`) injected.
- Works with existing `QACLAN_FACTORY_SOCKET` env var mechanism.

## Open questions

- **Auth for factory API calls.** App API requires authentication. Factory definitions need an "auth" field: "use env var `ADMIN_API_KEY`" or "use the session state from `state.json`". Start with env var approach.
- **Non-REST apps.** Factory assumes HTTP API. Apps with DB-only access (no admin API) cannot use this pattern. Document the limitation. GraphQL mutation support is a stretch goal.
- **Factory dependency chains.** `create("order")` depends on a user. Define dependencies in the factory definition? Or rely on script to pass `user_id` explicitly? Explicit is simpler and less magical. Start explicit.

## Next concrete step

Add `factory_definitions` and `factory_instances` tables. Build the factory definitions CRUD UI. Build `POST /api/factory/create` and `POST /api/factory/cleanup/:script_run_id` routes. Implement a minimal Python `qaclan_factory.py` client. Test end-to-end against a real app API before wiring into the harness.
