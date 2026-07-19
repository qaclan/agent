# Postman/Bruno Export — Design

## Problem

qaclan has no way to hand a collection to a teammate on Postman or Bruno.
The only export path today is `cli/api_discovery/bruno_parser.py::
request_to_bru()`, wired to `POST /api/collections/<id>/export` and
`qaclan api export` — and it's partial: per-request `meta`+verb+`url`+
`headers`+`body:json` only. No folders, no auth, no other body modes, no
scripts, no assertions. No Postman export exists at all.

Goal: export a qaclan collection to a spec-compliant Postman v2.1 collection
or a Bruno `.bru` collection, round-tripping cleanly back into qaclan via
the parsers in `2026-07-18-postman-bruno-import-fidelity-design.md`, and
reporting (not silently dropping) whatever a target format genuinely can't
represent.

## Scope

New `to_postman_collection()` exporter alongside the existing, extended
`request_to_bru()`. Extends `POST /api/collections/<id>/export` and
`qaclan api export` with a format switch. Out of scope: OpenAPI export
(separate, already exists, different data source).

## Format targets

- **Postman**: Collection Format **v2.1.0**
  (`schema: https://schema.postman.com/json/collection/v2.1.0/collection.json`)
  — the de facto universal standard (Newman, most third-party tool
  importers), and the shape `postman_parser.py` already expects, so
  export/reimport share one schema understanding.
- **Bruno**: legacy **`.bru`** text format, not the v3.1+ YAML default —
  matches `bruno_parser.py`, so export/reimport share one format.

## A. Path variables

Reverse of import spec §A: qaclan `{param}` → Postman `:param` in the URL
path plus a matching `url.variable[]` entry (`{key, value}`); → Bruno
`:param` in the URL plus a `params:path` block entry. `{{VAR}}` env refs
pass through unchanged — both formats support the same syntax natively.

## B. Folders

`api_folders` tree (via `parent_folder_id`) → Postman nested `item`
(item-group) structure, built recursively top-down from `FolderRepo`'s
tree; → Bruno **actual directory tree** — one subfolder per `api_folders`
node, one `.bru` file per request inside it. This matches Bruno's native
on-disk model directly, no synthetic nesting needed.

## C. Collection-level variables

`collection_vars` → Postman collection-root `variable[]`
(`{key, value, type:"string"}` per row); → Bruno root `collection.bru`
file, `vars:pre-request { key: value }` block. `collection.bru` is written
alongside the request-file tree from §B, at the collection root.

## D. Environments

qaclan `environments`/`env_vars` (multiple per project) → Postman separate
`*.environment.json` file per environment (Environment schema v2.1:
`values: [{key, value, type:"default", enabled: true}]`, `_postman_variable_scope: "environment"`);
→ Bruno `environments/<name>.bru` files inside the collection folder
(`vars { key: value }` block). Export UI offers a checkbox per environment;
default selection is the one environment linked via
`api_collections.env_name`, if set.

## E. Auth

Reverse of import spec §D:

| qaclan `auth_type` | → Postman/Bruno |
|---|---|
| `bearer`, `basic`, `api_key` | direct, same field names both directions |
| `oauth2` | direct, `client_credentials` grant only — matches the only grant qaclan itself supports, no loss |
| `inherit` | Postman: omit `auth` block (parent/collection auth applies — native Postman semantic). Bruno: `auth: inherit` (exists natively in the verb block) |
| collection-level `api_collections.auth_type`/`auth_config` | → Postman collection-root `auth` block; → Bruno `collection.bru`'s `auth { mode: ... }` + `auth:<mode> { ... }` sub-block (per §C) |

`none` is never round-tripped as a fabricated auth block — it maps to
`noauth` (Postman) / omitted `auth:` (Bruno).

## F. Body modes

Reverse of import spec §E — direct and lossless for `raw`, `form`,
`multipart` text fields, and `graphql`.

**Hard limit, both directions, not fixable**: multipart file fields.
qaclan stores actual file bytes (base64 in `value` when `is_file: true`).
Neither the Postman schema (`formdata` `type:"file"` takes only a `src`
path reference, no inline bytes) nor Bruno's `.bru` format (`@file(path)`
reference, same limitation) can hold inline file content. Exported file
fields become a path placeholder plus an export warning: "re-attach file:
`<fieldname>` manually in the target tool." This is a format ceiling in
Postman/Bruno themselves, not something qaclan's exporter can work around.

## G. Pre/post scripts — reverse literal call rewrite

Mirrors import spec §F exactly, reversed. qaclan's DB always holds native
`qc.*` JS (established as the single point of truth by the import design);
export regenerates foreign syntax deterministically from that text — no
runtime polyfill, no preserved "original foreign script" to fall back to,
because after import there no longer is one for the converted portion.

| qc.* call | → Postman | → Bruno |
|---|---|---|
| `qc.set(k,v)` | `pm.environment.set(k,v)` | `bru.setVar(k,v)` |
| `qc.test(name, fn)` | `pm.test(name, fn)` | bare `test(name, fn)` |
| `qc.setHeader(k,v)` | `pm.request.headers.add({key:k,value:v})` | `req.setHeader(k,v)` |
| `qc.getHeader(k)` | `pm.request.headers.get(k)` | `req.getHeader(k)` |
| `qc.setParam(k,v)` | `pm.request.url.addQueryParams({key:k,value:v})` | Bruno equivalent param setter |
| `qc.getParam(k)` | `pm.request.url.query.get(k)` | Bruno equivalent param getter |
| `response.json()` | `pm.response.json()` | `res.body` (Bruno auto-parses; drop the call syntax) |
| `response.text()` | `pm.response.text()` | `typeof res.body === 'string' ? res.body : JSON.stringify(res.body)` |
| `response.headers` | `pm.response.headers` | `res.headers` |
| `response.status` | `pm.response.code` | `res.status` |

`qc.expect(condition, message)` has no recoverable chain form (the original
matcher shape was collapsed to a plain boolean at import time) — export
regenerates a generic, always-correct equivalent rather than guessing the
original chai matcher:

- Postman: `pm.test(message, () => { if (!(condition)) throw new Error(message); })`
- Bruno: `test(message, () => { if (!(condition)) throw new Error(message); })`

Raw/unconverted foreign text that was left untouched at import time (calls
outside the rewrite table, e.g. `pm.sendRequest`) is already native
foreign syntax — passes through export unchanged, no reverse mapping
needed.

Python `pre_script`/`post_script` (`pre_lang`/`post_lang == "python"`):
neither Postman nor Bruno support any non-JS scripting. Omit entirely +
export warning: "pre/post script is Python, not supported by `<format>`."
No transliteration attempted — out of scope, too unreliable to be worth it.

## H. Assertions

- **→ Bruno**: native `assert {}` block, reverse of import spec §G's
  mapping (path and op tables both invert directly: `eq→eq`, `ne→neq`,
  `lt→lt`, `gt→gt`, `contains→contains`, `matches→matches`; `type:"status"`
  → `res.status`, `type:"header"` → `res.headers.<key>`, `type:"json_path"`
  → `res.body<path-without-$>`, `type:"response_time"` → `res.responseTime`).
  Lossy spot: `matchMode: "any"`/`"all"` (json_path assertions over an
  array) has no Bruno equivalent — Bruno's assert always checks one value.
  Export as first-match only + warning; this genuinely can't round-trip.

- **→ Postman**: no declarative assert block exists in the v2.1 schema at
  all — assertions must be codegen'd into the `event[listen="test"]
  .script.exec` array as `pm.test(...)` snippets:

  | qaclan type/op | generated line |
  |---|---|
  | `status`/`eq` | `pm.test("status is <value>", () => pm.response.to.have.status(<value>))` |
  | `header`/op | `pm.test(..., () => { const v = pm.response.headers.get('<key>'); if (!(<op-expr>)) throw new Error(...); })` |
  | `json_path`/op | same pattern, `v = pm.response.json()<path>` |
  | `response_time`/op | `if (!(pm.response.responseTime <op> <value>)) throw ...` |
  | `body_text`/`contains` | `if (!pm.response.text().includes(<value>)) throw ...` |

  Each generated snippet is a plain `if (!(cond)) throw new Error(...)`
  body inside `pm.test(name, fn)`, not chai chains — consistent with how
  `qc.expect` is regenerated in §G, and avoids re-inventing a second
  codegen style for the same underlying idea.

## Wiring

- `web/api/routes/collections.py`'s existing `POST
  /api/collections/<col_id>/export` gains a `?format=bruno|postman` query
  param (default `bruno`, preserving current behavior). Bruno path keeps
  streaming a zip of `.bru` files (now with real subfolders); Postman path
  streams a single `.json` file (the whole collection, since Postman
  collections are one file, not one-file-per-request).
- `cli/commands/api_cmd.py`'s `qaclan api export <collection> -o <dir>`
  gains `--format postman|bruno` (default `bruno`, same reasoning).

## Testing

No automated test suite in this repo. Manual: build one qaclan collection
exercising every row above (nested folders 2+ levels, all 4 auth types +
`inherit`, every body mode incl. a multipart file field, a JS post_script
using every rewritten `qc.*` call, a Python post_script, all 5 assertion
types incl. one `matchMode: "any"`). Export to both formats, then:

1. Validate the Postman JSON against the v2.1.0 schema
   (`schema.postman.com/json/collection/v2.1.0/collection.json`).
2. Reimport both exports via qaclan's own parsers, diff the resulting
   requests against the originals — this is the primary, testable
   round-trip acceptance criterion.
3. If Newman or a real Postman/Bruno install is available, actually run
   one exported request in the real tool and confirm the codegen'd
   `pm.test`/`assert{}` logic executes as expected — validates the codegen
   against the real runtime, not just qaclan's own reimport.

Cross-tool round-trip (Postman → qaclan → back to Postman, diffed) is
explicitly best-effort only. Known lossy spots, already flagged inline
above: multipart file bytes, `matchMode: "any"/"all"`, Python scripts,
auth types outside qaclan's 4 supported ones, `gte`/`lte` approximation.
