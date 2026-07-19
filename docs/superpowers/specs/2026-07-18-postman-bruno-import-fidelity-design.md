# Postman/Bruno Import Fidelity — Design

## Problem

`cli/api_discovery/postman_parser.py` and `bruno_parser.py` produce requests
that look right in the UI but mostly don't run correctly:

- Path variables (`:var`) are never converted to qaclan's `{var}` syntax or
  extracted into `path_params` — they pass through as literal broken text.
- Folder trees (Postman `item`-group nesting, Bruno directory structure) are
  completely discarded; everything flattens into one qaclan collection per
  top-level Postman folder / Bruno upload, with no `api_folders` rows at all.
- `pre-request`/`script:pre-request` events are dropped entirely — only the
  `test`/`post-response` event becomes `post_script`.
- Auth blocks (`bearer`/`basic`/`apikey`/`oauth2`/etc.) are never read —
  `auth_type` is hardcoded to `"none"`.
- Collection-level variables (Postman `variable[]`, Bruno `vars`) are
  discarded, even though qaclan has a live `collection_vars` table + UI tab
  for exactly this.
- Imported `pm.*`/`bru.*` script calls reference globals qaclan's sandbox
  never binds (only `qc.*` exists) — scripts silently fail at run time.
- Bruno's declarative `assert {}` blocks are parsed with a naive
  `split(None, 2)` and an incomplete operator map; most assert lines
  mis-evaluate or silently fall back to `eq`.

Goal: importing a real-world Postman collection or Bruno collection should
produce requests that run correctly with no manual rework, and any feature
that genuinely can't be converted should be reported, not silently dropped.

## Scope

Both parsers (`postman_parser.py`, `bruno_parser.py`) and the save layer
(`discovery_service.py::_save_requests`/`import_postman`/`import_bruno`).
Out of scope: HAR/OpenAPI import (unaffected), export (separate spec:
`2026-07-18-postman-bruno-export-design.md`).

## A. Path variables

qaclan URL syntax: `{param}` for path params (matched by `_PATH_PARAM_RE` in
`cli/api_runner.py`), `{{VAR}}` for env/state vars. Postman and Bruno both
use `:var` for path segments.

Both parsers: regex `:([A-Za-z_]\w*)` over the URL path portion (not
query string) → replace with `{$1}`, collect into
`path_params: [{key, value, enabled: true}, ...]`.

- Postman: seed `value` from `url.variable[]` entries when present (Postman
  stores `:var` declarations there with a `value` field); else empty.
- Bruno: seed `value` from the `params:path` block (currently unread by
  `bruno_parser.py` at all — must add a section reader for it).
- `{{var}}` segments (Postman/Bruno variable refs) pass through unchanged —
  already qaclan-compatible syntax, no conversion needed.

## B. Folders

Neither parser emits folder structure today, and `_save_requests` has no
folder-creation logic — confirmed by reading `discovery_service.py`:
`import_postman`/`import_bruno` group requests by a single `collection_name`
tag into one flat qaclan collection, full stop.

Changes:

1. Both parsers emit `folder_path: [name, ...]` (root → leaf) per request
   instead of discarding the folder chain. Postman: derived from nested
   `item`-group `name` fields. Bruno: caller must supply relative paths per
   file (`{name: "Auth/Login.bru", content: ...}`); `import_bruno`'s
   `bru_files` param already accepts a `name` per file — split on `/` for
   the folder chain, drop the leaf as the request name.
2. `_save_requests` (or a new helper, `_resolve_folder_path`) walks the
   unique `folder_path` values per import batch, calling
   `FolderRepo.create(project_id, collection_id, name, parent_folder_id)`
   top-down, memoized on `tuple(path)` so repeated paths across requests
   reuse the same folder instead of duplicating. `FolderRepo.create` has no
   depth limit (`parent_folder_id` is a plain self-referential FK), so
   arbitrary nesting works with one `create()` call per unique folder node.
3. Resulting `folder_id` is attached to each request dict before
   `RequestRepo.create`.

## C. Collection-level variables

Postman `variable[]` (collection root) and Bruno `vars` block (collection
level, not per-request) → one `CollectionVarsRepo.upsert(collection_id, key,
initial_value)` call per entry. This populates the existing "Variables" tab
(`collection-detail-view.js`) with no new UI work — the table and its full
read/write/sync path (`web/api/repositories/collection_vars_repo.py`,
`web/api/routes/collections.py:141-185`, run-time seeding in
`runner_service.py`) already exist and are live; they've simply never been
written to by import.

## D. Auth

qaclan supports exactly 4 types + `inherit` (`_apply_auth` in
`cli/api_runner.py`):

| qaclan `auth_type` | `auth_config` shape |
|---|---|
| `bearer` | `{"token": "..."}` |
| `basic` | `{"username": "...", "password": "..."}` |
| `api_key` | `{"key": "X-API-Key", "value": "...", "in": "header"\|"query"}` |
| `oauth2` | `{"token_url", "client_id", "client_secret"}` — **client_credentials grant only**, no refresh |

Mapping:

| Postman/Bruno auth | → qaclan |
|---|---|
| `bearer` | `bearer {token}` — direct |
| `basic` | `basic {username,password}` — direct |
| `apikey` | `api_key {key,value,in}` — Postman/Bruno attribute names already match |
| `oauth2`, grant=`client_credentials` | `oauth2 {token_url,client_id,client_secret}` — direct |
| `oauth2` other grants, `oauth1`, `digest`, `awsv4`, `ntlm`, `hawk`, `edgegrid`, `wsse` | **unsupported** — `auth_type="none"`, original block preserved in an import warning (see §H), not silently dropped |
| `noauth` / absent (Postman implicit inheritance) | `auth_type="inherit"` at request level |
| Collection-root `auth` block (Postman `collection.auth`, Bruno root vars-file `auth`) | same mapping table, written to `api_collections.auth_type`/`auth_config` |

## E. Body modes

| Source | qaclan `body_type` | Notes |
|---|---|---|
| Postman `raw` / Bruno `body:json`,`text`,`xml`,`sparql` | `raw` | direct |
| `urlencoded` / `form-urlencoded` | `form` | direct, drop `disabled` items |
| Postman `formdata` text fields / Bruno `multipart-form` text fields | `multipart`, item `{key,value,enabled,is_file:false}` | direct |
| Postman `formdata` `type:"file"` | `multipart`, item `is_file:true` | `src` is a local path on the exporting machine, not portable. If it resolves to a readable file at import time, base64-encode into `value`; else empty `value` + import warning "re-attach file: `<fieldname>`" |
| `graphql` (Postman) / `graphql`+`graphql:vars` (Bruno — currently unhandled at all) | `graphql`, `{"query", "variables"}` | direct; `cli/api_runner.py` already sends this correctly as a JSON POST |
| Bruno `multipart-form` file entries (`@file(path)` refs) | `multipart`, `is_file:true` | same portability caveat as Postman file fields |

## F. Pre/post scripts — literal call rewrite (not a runtime shim)

Decision: rather than binding a `pm`/`bru` proxy object at execution time,
**rewrite the stored script text once, at import**, replacing recognized
foreign calls with their `qc.*` equivalent. The DB always holds native
`qc.*` JS — single point of truth, no runtime translation layer, and export
(spec 2) reverses the same table to regenerate foreign syntax deterministically.

Both `prerequest`/`script:pre-request` and `test`/`script:post-response`
events now map to `pre_script`/`post_script` respectively — today only the
`test` event is even read.

Rewrite table (JS only — Postman/Bruno scripts are always JS; qaclan's
Python pre/post scripts have no foreign equivalent to import from):

| foreign call | → qc.* |
|---|---|
| `pm.environment.set(k,v)`, `pm.variables.set(k,v)`, `bru.setVar(k,v)`, `bru.setEnvVar(k,v)` | `qc.set(k,v)` |
| `pm.test(name, fn)`, bare `test(name, fn)` (Bruno/chai global) | `qc.test(name, fn)` |
| `pm.request.headers.add({key,value})`, `req.setHeader(k,v)` | `qc.setHeader(k,v)` |
| `pm.request.headers.get(k)`, `req.getHeader(k)` | `qc.getHeader(k)` |
| `pm.request.url.addQueryParams(...)`, Bruno equivalent | `qc.setParam(k,v)` |
| `pm.request.url.query.get(k)` | `qc.getParam(k)` |
| `pm.response.json()` | `response.json()` |
| `pm.response.text()` | `response.text()` |
| `pm.response.headers` | `response.headers` |
| `pm.response.status`/`pm.response.code`, Bruno `res.status` | `response.status` (JS) |

`.expect` needs pattern matching, not literal substitution — `pm.expect(x)`
returns a chainable chai object, `qc.expect(condition, message)` takes a
plain boolean. Match `pm.expect(EXPR).to.CHAIN(...)` / bare
`expect(EXPR).to.CHAIN(...)` for a known chain-ending set and rewrite the
whole line:

| chain ending | rewritten condition |
|---|---|
| `.to.equal(y)` | `EXPR === y` |
| `.to.eql(y)` | `JSON.stringify(EXPR) === JSON.stringify(y)` |
| `.to.be.true` | `EXPR === true` |
| `.to.be.false` | `EXPR === false` |
| `.to.exist` | `EXPR !== undefined && EXPR !== null` |
| `.to.not.exist` | `EXPR === undefined \|\| EXPR === null` |
| `.to.include(y)` | `EXPR.includes(y)` |
| `.to.match(/re/)` | `/re/.test(EXPR)` |

→ `qc.expect(<rewritten condition>, "<original line as message>")`.

Anything not matching a known call or chain ending (`pm.sendRequest`,
`pm.cookies`, `pm.iterationData`, `bru.runRequest`, unrecognized `.expect`
chains, etc.) is left as raw, unconverted text in the stored script —
flagged in the import warnings (§H), not silently swallowed. It will error
at run time under qaclan's `qc`-only sandbox, same as today, but the user
now sees why.

## G. Assertions (Bruno only)

Postman has no declarative assert block — its assertions only exist as
script code, handled entirely by §F. Bruno's `assert { path: op value }`
block → qaclan `assertions[]`.

Path translation: `res.status` → `type:"status"`; `res.headers.<key>` →
`type:"header", key:"<key>"`; `res.responseTime` → `type:"response_time"`;
anything else (bare path or `res.body...`) → `type:"json_path",
path:"$.<rest>"` (dot-path to `$.`-prefixed JSONPath is mechanical).

Op mapping — qaclan's backend op set is exactly `eq, ne, lt, gt, contains,
exists, not_exists, matches` (no `gte`/`lte`):

| Bruno op | → qaclan op | note |
|---|---|---|
| `eq` | `eq` | |
| `neq` | `ne` | |
| `gt`, `lt`, `contains` | direct | |
| `gte` | `gt` with value − 1 (numeric only) | flag as approximation in warnings |
| `lte` | `lt` with value + 1 (numeric only) | flag as approximation |
| `matches` | `matches` | |
| `isJson`, `isString`, `isNumber`, `isBoolean`, `isArray` | unsupported | flagged, not converted |

## H. Import warnings

Every gap above that can't be cleanly converted (unsupported auth type,
gte/lte approximation, unmatched script call, file field needing
re-attachment, unmapped assert op/type-check) is collected into a
`warnings: [{request_name, detail}]` list, returned alongside
`{"imported": N}` from `import_postman`/`import_bruno`, and rendered in the
existing import-preview UI (`2026-06-25-import-preview-flow.md`'s
`request-review-modal.js`) as a per-item banner. No silent data loss.

## Testing

No automated test suite in this repo. Manual: build one Postman v2.1
fixture collection and one Bruno folder exercising every row above (nested
folders 2+ levels deep, `:var` paths, all 4 supported auth types + 1
unsupported type, every body mode incl. a file field, pre+post scripts
using every rewritten call plus one unmatched call, Bruno asserts incl.
`gte`). Import via both CLI and web UI, verify resulting `api_requests` /
`api_folders` / `collection_vars` rows, and run the imported collection live
to confirm scripts execute correctly (rewritten `qc.*` calls fire, auth
injects, path params substitute, assertions evaluate).
