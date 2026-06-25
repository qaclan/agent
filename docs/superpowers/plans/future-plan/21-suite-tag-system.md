# 21 - Suite / Tag System

Deep-dive on feature #21 from [feature-ideas.md](../feature-ideas.md). Covers how tags layer on top of the existing suite model, what tags solve that suites don't, and how the two concepts coexist.

---

## Existing suite model — what we have

QAClan already has a full suite system:

- `suites` table — named collection of scripts, ordered, per-project.
- `suite_items` table — many-to-many between suites and scripts, with `order_index`.
- `suite_runs` — execution record for a suite run.

A user creates a suite called "smoke", adds 5 scripts, runs it. This works well.

**What suites solve:** a permanent, curated, ordered set of scripts with a name.

**What suites do not solve:**
- Ad-hoc grouping ("run all checkout-related scripts, regardless of which suite they're in").
- Cross-suite filtering ("show me every script tagged `@flaky`").
- Lightweight labeling without creating a new suite for every combination.

## The tags gap

Suppose a project has 30 scripts across 3 suites. The team wants to:

- Run only `@smoke` scripts before every deploy.
- Run all `@checkout` scripts after a payment refactor.
- Run nothing `@wip` (work in progress, not stable yet).

With suites only: create a "smoke" suite, a "checkout" suite, a "no-wip" suite — and keep them in sync manually. Every time a script is added, update every relevant suite. Fragile.

With tags: tag scripts on creation. Run by tag. Suites still exist for curated, ordered, permanent flows. Tags handle everything else.

## Example

```
Scripts tagged:
  login-flow          @smoke @auth
  register-flow       @smoke @auth
  checkout-standard   @smoke @checkout
  checkout-guest      @checkout
  password-reset      @auth
  admin-dashboard     @wip
  payment-refund      @checkout @wip

# Run only smoke tests (3 scripts):
qaclan run --tags smoke

# Run checkout but skip WIP (2 scripts):
qaclan run --tags checkout --exclude wip

# UI: filter script list by tag @auth → shows 3 scripts → "Run all @auth" button
```

## Impact

| Dimension | Effect |
|---|---|
| Suite maintenance | Stop creating suites for every run profile. Tags replace the "quick suite" pattern. |
| Ad-hoc runs | Developers can run scripts by label without navigating suite management. |
| Scheduled run targeting | Scheduler (feature #8) can target a tag, not just a suite. "Run @smoke every 30 min." |
| Script organization | Tags visible in the script list provide quick orientation. "What does this script cover?" |
| CI generator | GitHub Actions generator (feature #17) can target a tag: `qaclan run --tags smoke`. |

Overall: **medium-high impact**. Low implementation cost. Tags are a natural complement to suites, not a replacement.

## Tags vs suites — when to use which

| Use case | Suites | Tags |
|---|---|---|
| Ordered E2E flow (login → cart → checkout) | Yes — order matters | No |
| Shared state across scripts | Yes — suite_items defines the state thread | No |
| Curated, named, permanent set | Yes | Maybe (if unsorted) |
| Ad-hoc filtering | No | Yes |
| Cross-project or cross-suite grouping | No | Yes |
| "Skip WIP" during a run | No | Yes |
| Scheduled run by category | Clunky (must name the suite) | Natural |

## Schema

Tags stored as a JSON array on the `scripts` table. No separate tag table for v1.

```sql
-- Migration: add tags column to scripts
ALTER TABLE scripts ADD COLUMN tags TEXT DEFAULT '[]';
-- Stored as JSON array: '["smoke","auth","checkout"]'
```

Pros of JSON array: simple, no join needed, easy to read in queries.
Cons: cannot query "all scripts with tag X" without JSON functions. SQLite has `json_each()` which handles this since SQLite 3.38+.

Alternative: a `script_tags` many-to-many table. More relational, better for complex queries. But adds migration complexity. Start with JSON array; migrate to M2M table if query performance becomes an issue.

## Tag filtering query

```sql
-- Find scripts with tag "smoke"
SELECT s.* FROM scripts s, json_each(s.tags) t
WHERE t.value = 'smoke'
  AND s.project_id = ?;
```

## CLI integration

New run mode: `qaclan run --tags <tag>[,<tag>...] [--exclude <tag>]`

This creates an ephemeral `suite_run` just like `qaclan suite run <name>` but assembles the script list from the tag query instead of from `suite_items`. The execution path ([web/routes/runs.py](../../web/routes/runs.py)) is the same — just a different script list assembly step.

The result appears in run history as "Tag run: @smoke" (not tied to a named suite).

## UI integration

**Script list view:**
- Tag chips displayed on each script card.
- Tag filter bar at top of script list. Click a tag → filters list.
- "Run all filtered scripts" button appears when one or more tags are selected.

**Script create/edit:**
- Tag input field with autocomplete from existing tags in the project.
- Tags are free-form strings, no pre-registration required.

**Suite detail view:**
- "Save as suite" button when running by tag. Creates a new suite from the current tag-filtered script set. Bridge between the two models.

**Scheduler (feature #8):**
- Schedule target: "Suite" or "Tag" selector.
- If "Tag": enter tag name. Scheduler assembles script list at run time (not at schedule creation). Scripts added later with the same tag are automatically included in future scheduled runs.

## Implementation path

### Phase 1 — tag column + UI

- Migration: add `tags TEXT DEFAULT '[]'` to `scripts` table.
- Script create/edit UI: tag input with autocomplete.
- Script list: display tag chips, tag filter bar.

### Phase 2 — run by tag

- New route: `POST /api/runs/tag` with `{tags: ["smoke"], exclude: ["wip"]}`.
- Assembles script list from tag query. Delegates to existing `execute_run` logic.
- UI: "Run @tag" button in script list after tag filter is applied.

### Phase 3 — CLI

- Add `--tags` and `--exclude` flags to CLI run command in [cli/commands/](../../cli/commands/).
- `qaclan run --tags smoke --exclude wip` → calls tag run API or executes directly.

### Phase 4 — scheduler + CI generator integration

- Scheduler: add "Tag" option alongside "Suite" for schedule targets.
- CI generator: add `--tags` to generated workflow command.

## Open questions

- **Tag namespace collisions.** Tags are free-form strings. "smoke", "Smoke", "SMOKE" — are these the same tag? Normalize to lowercase on save. Display as entered.
- **Tag suggestions.** Autocomplete pulls from `json_each(tags)` across all scripts in the project. Show frequency count: "@smoke (12 scripts)".
- **Tag ordering in runs.** When running by tag, scripts have no defined order (unlike suite_items). Default: alphabetical by script name. Override: drag-to-reorder in the "Run by tag" modal, which optionally saves as a suite.
- **Tag rename.** Renaming a tag requires updating every script that uses it. Add a bulk rename tool: "Rename @auth to @authentication across all scripts". This is a simple JSON string replace in the `tags` column.

## Next concrete step

Add `tags` column migration to [cli/db.py](../../cli/db.py). Add tag input to script create/edit form. Add tag chip display to script list. Implement `GET /api/tags?project_id=` route for autocomplete. Phase 1 only — no tag-based runs yet. Validate the tagging UX before building the run machinery.
