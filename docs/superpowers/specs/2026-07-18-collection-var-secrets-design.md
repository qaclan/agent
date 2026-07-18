# Collection Variable Secrets — Design

## Problem

Environment variables (`env_vars`) support a `is_secret` flag: value is encrypted at rest, displayed masked in the UI, and revealable via `GET /api/envs/<env_name>/vars/<key>/reveal`. Collection-scoped variables (`collection_vars`, seeded before each collection run for `{{VAR}}` tokens set by post-scripts) have no equivalent — every value is stored and shown in plaintext.

Goal: give `collection_vars` the same secret-handling UX and storage guarantees as `env_vars`, without conflating the two (a collection is not tied to a single environment — `env_name` can be null or switched independently), and hand off the matching contract change to the separate `qaclan-server` repo.

## Approach

Give `collection_vars` its own `is_secret` column, its own encryption, and its own reveal endpoint scoped by `collection_id` — mirroring `env_vars`' implementation pattern rather than reusing its table or route (a collection var's identity is `(collection_id, key)`, not `(env_name, key)`, so the existing `/api/envs/<env_name>/vars/<key>/reveal` route cannot address it).

Rejected alternatives:
- **Store collection secrets as `env_vars` rows** — conflates two independent concepts; a collection's `env_name` can be null or reassigned, so there's no stable environment to anchor the secret to.
- **UI-only masking, no encryption at rest** — doesn't match the actual `env_vars` behavior this is meant to parallel (real encryption, not cosmetic).

## 1. Data model & encryption

- New migration in `cli/db.py`: `ALTER TABLE collection_vars ADD COLUMN is_secret INTEGER NOT NULL DEFAULT 0`, registered in `_run_migrations()` alongside the existing `_migrate_*` functions.
- No new table. The existing `initial_value TEXT` column holds ciphertext when `is_secret = 1`, plaintext otherwise — same dual use as `env_vars.value`.
- Encryption via the existing `cli/crypto.encrypt`/`decrypt` (Fernet, key at `~/.qaclan/secret.key`, per-device).

## 2. Backend — `web/api/repositories/collection_vars_repo.py`

- `list(collection_id)` — unchanged shape plus `is_secret`; returns the **raw** stored value (plaintext or ciphertext), no masking. This method is also the base for `as_seed_dict()`, so it must not lose information.
- `upsert(collection_id, key, initial_value, is_secret=0, unchanged=False)`:
  - `unchanged=True` on a row whose stored `is_secret=1`: keep the existing ciphertext, ignore the incoming `initial_value` (mirrors `envs.py`'s `unchanged` handling for masked-and-untouched rows).
  - Otherwise: if `is_secret` and the incoming value isn't already ciphertext (`cli.crypto.is_encrypted`), encrypt before storing.
- `as_seed_dict(collection_id)` — decrypts any `is_secret` row before returning `{key: value}`, mirroring `cli/env_loader.py:load_env_vars`. This is what actually seeds `qaclan_vars` for a run, so it must yield plaintext.

## 3. Backend — `web/api/routes/collections.py`

- `GET /api/collections/<col_id>/vars` — after calling the repo's `list()`, replace `is_secret` rows' value with the same `MASKED_DISPLAY = "•" * 8` sentinel `web/routes/envs.py` already defines, before returning JSON. Masking happens in the route (display concern), not the repo, so `as_seed_dict()` keeps working.
- `PUT /api/collections/<col_id>/vars/<key>` — body gains `is_secret` (bool) and `unchanged` (bool), passed through to `upsert()`.
- New `GET /api/collections/<col_id>/vars/<key>/reveal` — same shape as `envs.py:reveal_var`, scoped by `collection_id`: look up the `collection_vars` row for `(col_id, key)`, `decrypt()` if `is_secret`, return `{"ok": true, "key": key, "value": value}` with `Cache-Control: no-store`.

## 4. Frontend — `web/static/api/views/collection-detail-view.js`, `_buildVarsTab`

Each variable row gains:
- A secret checkbox column (same as `env-row-secret`).
- `type="password"` on the value input when secret.
- The same masked/edited state machine as `app.js`'s `_envVarRowHTML`/`_onEnvValueFocus`/`_onEnvValueEdit`/`_onEnvSecretToggle` (`app.js:4712-4774`): first focus on a masked row clears the placeholder; unticking "secret" on a still-masked row fetches the real value via the new reveal endpoint (scoped by `col.id`, not an env name) before flipping the input to text; any edit or toggle marks the row no-longer-masked so the next save sends a real value instead of `unchanged: true`.

Not extracted into a shared helper module — `app.js`'s env page and `collection-detail-view.js` are separate view layers already; the duplicated ~60 lines match existing codebase style rather than introducing a new shared abstraction for two call sites.

`_saveRow()` sends `{ initial_value, is_secret, unchanged }`; skip the PUT entirely when the row is masked and untouched (matches the existing skip‑unless‑edited spirit, avoids re-encrypting a value we never decrypted).

## 5. Cloud sync (this repo's client side)

- `cli/sync.py:sync_collection_vars_to_cloud` — add `is_secret` to each pushed var (currently only sends `key`/`initial_value`). Value pushed as stored (ciphertext when secret), same semantics as `sync_env_vars_to_cloud`.
- `cli/commands/pull.py` collection_vars pull handler (~line 280) — accept and persist `is_secret` on insert/update, mirroring the `env_vars` pull handler at `pull.py:324-343`.
- **Known inherited limitation, not introduced or fixed here:** the Fernet key is per-device. A secret var pushed from one machine and pulled on another will not decrypt there — the decrypt call already silently falls back to raw ciphertext on failure (`except Exception: pass` pattern in `env_loader.py`). This is identical to today's `env_vars` behavior; out of scope to fix as part of this feature.

## 6. qaclan-server contract update

Edit `docs/superpowers/plans/2026-07-13-qaclan-server-api-testing-sync-plan.md` (the standing implementation contract for the `qaclan-server` repo, not yet deployed there):
- §1 schema: add `is_secret BOOLEAN NOT NULL DEFAULT false` to `cloud_collection_vars`.
- §2.7 `POST /api/sync/collection-vars`: document `is_secret` in the per-var payload; note the server stores the value as delivered and never attempts to decrypt it.
- §3 pull/workspace `collection_vars` shape: add `is_secret` to the returned objects.

## 7. CLAUDE.md standing rule

Add a new "Maintenance rule" bullet under the **Cloud sync** paragraph:

> Any schema or payload change to a cloud-synced entity (a table with a `cloud_id` column, or a changed push/pull shape in `cli/sync.py` / `cli/commands/pull.py`) must be reflected in the matching `docs/superpowers/plans/*qaclan-server*sync-plan*.md` contract doc in the same change. If no contract doc yet covers the touched entity, say so explicitly rather than let the two repos silently drift.

## Testing

No automated test suite in this repo (per CLAUDE.md). Manual verification: create a collection var, mark secret, confirm masked display, reveal via the new endpoint, confirm plaintext decrypts correctly, run the collection and confirm the post-script-visible `{{VAR}}` resolves to plaintext, confirm cloud push payload includes `is_secret` (mock or inspect the request).
