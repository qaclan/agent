# Collection variable secrets + env/collection source styling

Date: 2026-07-19

## Context

API collections currently support two variable sources: `environments` (project-scoped, `env_vars` table, one active environment per collection via `api_collections.env_name`) and `collection_vars` (per-collection, plaintext only). Resolution at request time (`cli/api_runner.py:resolve_vars`) checks `env_vars` before `qaclan_vars` (which is seeded from `collection_vars` and mutated by scripts/extractors).

Frontend variable suggestions (`request-editor-view.js`, `collection-detail-view.js`) already merge both sources into one list tagged `group: 'Environment' | 'Collection'`, feeding a shared var-picker and inline-var-drop component. `{{var}}` tokens in inputs are rendered through `var-token-overlay.js`, currently colored only by resolution status (`--success` green if known, `--danger` red if missing) — there is no visual distinction of *which* source a resolved token came from, only a text label in the hover tooltip.

Environment variables support secrets: `env_vars.is_secret`, Fernet encryption via `cli/crypto.py` (key at `~/.qaclan/secret.key`, `enc:v1:` sentinel), masked display (`••••••••`), and a reveal-on-demand endpoint. Collection variables have no secret concept at all — no column, no encryption, always plaintext.

This spec covers two related gaps, both scoped to the API collections feature:

1. No visual distinction between env-sourced and collection-sourced resolved `{{var}}` tokens beyond tooltip text.
2. Collection variables cannot be marked/stored as secrets, unlike environment variables.

## Goals

- Resolved `{{var}}` tokens are visually distinguishable by source (environment vs collection), accessible beyond color alone (colorblind-safe badge).
- Collection variables support the same secret/encryption capability as environment variables: `is_secret` flag, encrypted storage, masked display, reveal endpoint.
- Secret support extends through the full lifecycle: creation/edit, suggestions/autocomplete (already source-agnostic on masking, just needs real data), request resolution, and Postman/Bruno import/export.

## Non-goals

- No change to the single-active-environment-per-collection model (out of scope; not requested).
- No new "global" or "local" variable scope tier — precedence stays two-tier (env > collection/state), as already documented in `docs/api-script-reference.md`.
- No CLI commands for managing collection var secrets unless a CLI surface for collection vars already exists (verify during planning; don't invent one if it doesn't).
- Bruno `.bru` import does not gain secret detection — Bruno's collection-var format (`vars:pre-request` block) has no secret marker, so there's nothing to read.

## Design

### 1. Schema

Add a migration in `cli/db.py` (following the existing `_migrate_var_picker` pattern):

```sql
ALTER TABLE collection_vars ADD COLUMN is_secret INTEGER DEFAULT 0
```

Secret values are encrypted using the existing `cli/crypto.py` primitives (`encrypt`/`decrypt`/`is_encrypted`, Fernet, `enc:v1:` sentinel) — same key file, same module, no new crypto code.

### 2. Backend

- `web/api/repositories/collection_vars_repo.py`: `upsert()` accepts `is_secret`; when `is_secret` is true and the incoming value isn't already encrypted, encrypt before storing. Support an `unchanged` sentinel value (mirroring `web/routes/envs.py`'s pattern) so the UI can resubmit a masked value without clobbering the stored ciphertext.
- `web/api/routes/collections.py`: `GET /collections/<id>/vars` masks `is_secret` values as `••••••••` before returning (mirror `envs.py`'s `get_env_vars` masking). New `GET /collections/<id>/vars/<key>/reveal` decrypts and returns plaintext with `Cache-Control: no-store` (mirror the env reveal endpoint).
- `web/api/services/runner_service.py`: `as_seed_dict()` (or its caller) decrypts `is_secret` collection var values when seeding `state["qaclan_vars"]` — request execution needs real plaintext, only display/list responses mask.
- If a CLI path for collection vars exists (verify during planning), extend it analogously; otherwise skip — don't add a CLI surface that isn't there today.

### 3. Import (Postman / Bruno → collection_vars)

- `cli/api_discovery/postman_parser.py`: when parsing `collection.get("variable", [])`, read `v.get("type") == "secret"` and set `is_secret=True` on the resulting dict (currently only `key`/`value` are read, `type` is discarded).
- `cli/api_discovery/bruno_parser.py`: no change — Bruno's `vars:pre-request` block has no secret marker, imported vars stay plaintext (`is_secret=False`).
- `cli/commands/pull.py`: propagate `is_secret` through to the `collection_vars` upsert (encrypting on write per §1/§2).

### 4. Export (collection_vars → Postman JSON / Bruno .bru)

Per explicit decision: secret collection vars export as **decrypted plaintext** (matches today's fidelity-first behavior for all other collection var data). This is a deliberate tradeoff, not an oversight — flagged to the user during design: exported files become as sensitive as a `.env` file and should be handled with the same care (avoid committing to git, sharing in chat, etc.).

- `cli/api_discovery/postman_exporter.py`: `to_postman_collection()` decrypts secret values before writing, and sets `"type": "secret"` instead of `"type": "string"` for those entries (so the type marker round-trips even though the value is exposed).
- `cli/api_discovery/bruno_parser.py`: `collection_bru()` decrypts secret values before writing (Bruno's `.bru` format has no type marker to set).

### 5. Frontend — surfacing `is_secret` for collection vars

`var-picker.js` and `inline-var-drop.js` already mask purely on `v.is_secret` regardless of `v.group` — no changes needed there. The only gap is two call sites hardcoding `is_secret: false` for the Collection group:

- `web/static/api/views/request-editor-view.js:60`
- `web/static/api/views/collection-detail-view.js:33`

Both change `is_secret: false` → `is_secret: !!v.is_secret`, once `GET /collections/<id>/vars` returns the real field (§2).

### 6. Token color + badge by source

`web/static/api/components/var-token-overlay.js`'s `_render()` currently assigns `var-tok--ok` / `var-tok--missing` based purely on whether the token name is known. Extend:

- When a token is `--ok`, look up its matched entry's `group` (already available via `getVarsList()`, already used in the tooltip builder) and additionally set `data-src="E"` (Environment) or `data-src="C"` (Collection), plus a modifier class `var-tok--env` / `var-tok--col`.
- Missing tokens are unaffected — source is unknown when a token can't be resolved, so no badge, existing red stays as-is.
- CSS (`web/static/style.css`, near the existing `.var-tok--ok`/`.var-tok--missing` rules ~line 1855): reuse `--accent` (existing blue) for `var-tok--env`; add one new custom property for collection, e.g. `--var-col: #a855f7` (violet), defined in `:root` and overridden in the existing `html[data-theme="light"]` block, following the same pattern as `--success`/`--danger`. Badge rendered via `.var-tok[data-src]::after { content: attr(data-src); ... }` — safe with the existing hover-tooltip hit-testing in `var-token-overlay.js` since `::after` content is inside the span's `getBoundingClientRect()`.
- This is additive to, not a replacement of, the ok/missing color — badge + hue communicate source, existing green/red-equivalent semantics for resolved/missing are preserved (exact color pairing to be finalized during implementation so ok/missing stays legible against both new hues).

### 7. Docs

- `docs/api-script-reference.md`: update the "Known gaps" note (currently states collection vars have no secret support) to reflect the new capability. Document the reveal endpoint and the export-plaintext caveat from §4.
- Per `CLAUDE.md`'s maintenance rule, any touched `pre_script`/`post_script`/`qc.`-related behavior must also be reflected there — this change doesn't alter script bindings themselves, only var storage/masking, so no `qc.*` binding changes are expected, but the doc update above is still required since it documents var secrecy behavior.

## Data flow summary

```
Create/edit collection var (UI)
  → POST/PUT /collections/<id>/vars {key, value, is_secret}
  → repo encrypts if is_secret (crypto.encrypt)
  → stored in collection_vars (ciphertext if secret)

List/suggest (UI)
  → GET /collections/<id>/vars
  → repo returns row, route masks is_secret values → "••••••••"
  → merged into getAllVars() with group: 'Collection', real is_secret
  → var-picker / inline-var-drop mask display (existing generic logic)
  → var-token-overlay colors token by group (env=blue+E, collection=violet+C)

Reveal (UI, explicit user action)
  → GET /collections/<id>/vars/<key>/reveal
  → repo decrypts (crypto.decrypt), Cache-Control: no-store

Run request
  → runner_service seeds qaclan_vars from as_seed_dict(), decrypting is_secret values
  → resolve_vars(text, env_vars, state) — env_vars still takes precedence over qaclan_vars, unchanged

Import (Postman)
  → variable[].type == "secret" → is_secret=True → encrypted on upsert

Export (Postman/Bruno)
  → decrypt is_secret values → write plaintext (+ type:"secret" marker for Postman)
```

## Testing

No automated test suite exists in this repo (per `CLAUDE.md`). Verification is manual, covering:

- Create a secret collection var → confirm masked in list view, suggestions dropdown, and var-picker.
- Reveal endpoint returns correct decrypted plaintext, response has `Cache-Control: no-store`.
- Running a request that references the secret var resolves the real value in the HTTP call.
- Export to Postman JSON: secret var appears as plaintext value with `"type": "secret"`.
- Export to Bruno `.bru`: secret var appears as plaintext value in `vars:pre-request` block.
- Import a Postman collection with a `"type": "secret"` variable → resulting collection var has `is_secret=1` and is encrypted at rest.
- Import a Bruno collection → collection vars remain plaintext, `is_secret=0`.
- Token overlay: env-sourced resolved token shows blue + "E" badge; collection-sourced resolved token shows violet + "C" badge; missing token shows red, no badge — check both light and dark themes.
- Editing an existing secret var without changing its value (resubmitting the masked placeholder) does not corrupt/clobber the stored ciphertext.
