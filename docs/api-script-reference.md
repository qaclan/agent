# API Pre/Post Script Reference

Source of truth: `cli/api_runner.py` (`_build_python_sandbox`, `_build_js_sandbox`, `_run_script_sandbox`, `_apply_extractor`).

**Maintenance rule:** whenever those functions change (new binding added/removed/renamed, new context field, new extractor behavior), update this doc in the same change. This doc must never drift from the code.

---

## Where scripts run

Each `pre_script` / `post_script` on an `api_requests` row runs as a **real subprocess** — the runtime venv's Python interpreter, or the runtime's Node binary — not an in-process eval. The runner wraps the user's script text with a generated header (bindings) and footer (writes result to a temp JSON file) and executes it with a 30s timeout. Output the sandbox understands is only what's written to that temp file: `headers`, `params`, `state`.

**Not actually sandboxed at the OS level.** Despite being called a "sandbox," there is no seccomp/container/restricted-builtins layer. A script can `import os`, `urllib.request`, read/write files, or import anything resolvable in the runtime's `node_modules`/venv site-packages. Treat scripts as trusted code, not untrusted user input.

---

## Pre-script (runs before the HTTP call)

Context available: current resolved `headers`, `params`, and `env` (active environment vars) — all three are bound as plain variables in both languages.

### Python (`pre_lang: "python"`)

| Name | Type | Does |
|---|---|---|
| `qc.set_header(key, value)` | method | Add/overwrite a request header before send |
| `qc.set_param(key, value)` | method | Add/overwrite a query param before send |
| `qc.get_header(key, default=None)` | method | Read back a header already staged (original or set earlier in this script), case-insensitive key match |
| `qc.get_param(key, default=None)` | method | Read back a query param already staged, exact key match |
| `qc.set(key, value)` | method | Write a value to shared state (`qaclan_vars`) — usable in pre-script too, e.g. to stamp a nonce for later steps |
| `qc.expect(condition, message="assertion failed")` | method | Record a pass/fail script assertion, shown alongside no-code assertion results |
| `qc.test(name, fn)` | method | Run `fn`; records one assertion named `name`, failed with `fn`'s exception message if it raises |
| `env` | dict | Active environment's `{{var}}` values, read-only |
| `os`, `json` | stdlib | Imported in the header, available to use |

```python
import time
qc.set_header("X-Timestamp", str(int(time.time())))
qc.set_param("nonce", str(int(time.time() * 1000)))

if env.get("environment_name") == "prod":
    qc.set_header("X-Strict-Mode", "1")

if not qc.get_header("X-Signature"):
    qc.set_header("X-Signature", "precomputed-sig")

qc.expect(qc.get_param("nonce") is not None, "nonce param set")
```

### JavaScript (`pre_lang: "js"`, runs via `node`)

| Name | Type | Does |
|---|---|---|
| `qc.setHeader(key, value)` | method | Add/overwrite a request header before send |
| `qc.setParam(key, value)` | method | Add/overwrite a query param before send |
| `qc.getHeader(key, default)` | method | Read back a header already staged, case-insensitive key match |
| `qc.getParam(key, default)` | method | Read back a query param already staged, exact key match |
| `qc.set(key, value)` | method | Write a value to shared state |
| `qc.expect(condition, message)` | method | Record a pass/fail script assertion |
| `qc.test(name, fn)` | method | Run `fn`; records one assertion named `name`, failed with the caught error's message if it throws |
| `env` | object | Active environment's `{{var}}` values, read-only |
| `require(...)` | function | Real Node `require` — can pull in anything resolvable, not restricted |

```js
qc.setHeader("X-Timestamp", Date.now().toString())
qc.setParam("nonce", Date.now().toString())

if (env.environment_name === "prod") qc.setHeader("X-Strict-Mode", "1")

if (!qc.getHeader("X-Signature")) qc.setHeader("X-Signature", "precomputed-sig")

qc.expect(qc.getParam("nonce") != null, "nonce param set")
```

---

## Post-script (runs after the HTTP response)

Context available: `response_body`, `response_headers`, `status_code`, plus the request's `headers`/`params`/`env`.

### Python (`post_lang: "python"`)

| Name | Type | Does |
|---|---|---|
| `response.json()` | method | Parses `response_body` as JSON (raises if not valid JSON) |
| `response.text()` | method | Raw response body string — never throws, use for non-JSON bodies |
| `response.headers` | attribute | Dict of response headers |
| `response_body` | variable | Raw response body string (same as `response.text()`) |
| `response_headers` | variable | Same dict as `response.headers` |
| `status_code` | variable | Int status code (Python has no `response.status` — use this top-level var) |
| `env` | dict | Active environment's `{{var}}` values, read-only |
| `qc.set(key, value)` | method | Extract/write a value to shared state — this is the primary way data flows into the next suite step |
| `qc.get_header(key, default=None)` / `qc.get_param(key, default=None)` | method | Read back the headers/params sent with the request that just ran |
| `qc.set_header(key, value)` / `qc.set_param(key, value)` | method | Still callable post-response, but have no effect on the request that already ran |
| `qc.expect(condition, message="assertion failed")` | method | Record a pass/fail script assertion, merged into the request's `assertion_results` alongside no-code assertions |
| `qc.test(name, fn)` | method | Run `fn`; records one assertion named `name`, failed with `fn`'s exception message if it raises |

```python
data = response.json()
qc.set("user_id", data["id"])
qc.set("auth_token", response.headers.get("x-auth-token", ""))
if status_code == 429:
    qc.set("rate_limited", "true")

qc.expect(status_code == 200, "status is 200")

def check_role():
    assert response.json()["role"] == "admin"
qc.test("role is admin", check_role)
```

### JavaScript (`post_lang: "js"`)

| Name | Type | Does |
|---|---|---|
| `response.json()` | method | Parses `response_body` as JSON |
| `response.text()` | method | Raw response body string — never throws, use for non-JSON bodies |
| `response.headers` | attribute | Dict of response headers |
| `response.status` | attribute | Int status code (JS, unlike Python, exposes this directly on `response`) |
| `env` | object | Active environment's `{{var}}` values, read-only |
| `qc.set(key, value)` | method | Write to shared state |
| `qc.getHeader(key, default)` / `qc.getParam(key, default)` | method | Read back the headers/params sent with the request that just ran |
| `qc.setHeader(key, value)` / `qc.setParam(key, value)` | method | Callable, no effect post-response |
| `qc.expect(condition, message)` | method | Record a pass/fail script assertion, merged into the request's `assertion_results` alongside no-code assertions |
| `qc.test(name, fn)` | method | Run `fn`; records one assertion named `name`, failed with the caught error's message if it throws |

```js
const data = response.json()
qc.set("user_id", data.id)
qc.set("token", response.headers["x-auth-token"])
if (response.status === 429) qc.set("rate_limited", "true")

qc.expect(response.status === 200, "status is 200")

qc.test("role is admin", () => {
  if (response.json().role !== "admin") throw new Error("role was not admin")
})
```

---

## No-code extractors (`pre_extractor` / `post_extractor`)

Alternative to writing a script — a list of `{name, path, prefix}` rules applied to a JSON response body via dot-path lookup (`a.b.0.c` style, no JSONPath operators).

- **`pre_extractor`** — runs before the pre-script, pulling values out of the *previous* request's response (`state["_last_response"]`) into `qaclan_vars`.
- **`post_extractor`** — runs after the HTTP call but before the post-script, pulling values out of *this* response.
- Script (`qc.set`) always runs after extractors and can override the same key.

```json
{"name": "user_id", "path": "data.id"}
{"name": "token", "path": "auth.token", "prefix": "Bearer "}
```

---

## Script assertions (`qc.expect` / `qc.test`)

Scripts can record pass/fail assertions alongside the no-code assertion system, instead of only setting variables. Each `qc.expect(...)`/`qc.test(...)` call appends `{type: "script", name, passed, error?}` to the script's `assertions` output; the runner merges these into the request's `assertion_results` list (same array the no-code assertions land in), and a failed script assertion fails the overall request the same way a failed no-code assertion does.

- `qc.expect(condition, message)` — one-line boolean check, no exception needed.
- `qc.test(name, fn)` — groups multiple checks under one named result; any exception (a failed `assert`/`raise` in Python, a `throw` in JS) is caught and recorded as a failure with the exception's message, so the script keeps running afterward.
- Pre-script and post-script assertions are both supported and pooled into the same `assertion_results` list — there's no separate "pre" vs "post" tag on the result.
- Still no expectation/matcher library (no `qc.expect(x).to.equal(y)` chaining) — pass a plain boolean or comparison expression.

```python
qc.expect(status_code == 200, "status is 200")

def check():
    users = response.json()["users"]
    assert len(users) > 0, "users list is empty"
qc.test("users not empty", check)
```

---

## Postman/Bruno import & export script conversion

Source of truth: `cli/api_discovery/script_rewrite.py` (`foreign_script_to_qc` for import, `qc_script_to_foreign` for export), consumed by `cli/api_discovery/postman_parser.py`, `bruno_parser.py`, and `postman_exporter.py`.

**Maintenance rule:** whenever the call tables in `script_rewrite.py` change (a new foreign call mapped/unmapped, a new `.expect()` chain ending supported, a new reverse mapping added), update this section in the same change.

Foreign scripts (Postman's `pm.*`, Bruno's `bru.*`/bare `test()`/`expect()`) are **not run through a compatibility shim at execution time**. Instead, import rewrites the stored script text once, in place, so `pre_script`/`post_script` always hold native `qc.*` JS in the DB — the single point of truth. Export reverses the same table to regenerate foreign syntax deterministically; it does not preserve or fall back to original foreign text, since after import there no longer is one for the converted portion.

**Import — literal call rewrite** (`foreign_script_to_qc`):

| Foreign call | → qc.* |
|---|---|
| `pm.environment.set(k,v)`, `pm.variables.set(k,v)`, `bru.setVar(k,v)`, `bru.setEnvVar(k,v)` | `qc.set(k,v)` |
| `pm.test(name,fn)`, bare `test(name,fn)` (Bruno/chai) | `qc.test(name,fn)` |
| `req.setHeader(k,v)` | `qc.setHeader(k,v)` |
| `req.getHeader(k)`, `pm.request.headers.get(k)` | `qc.getHeader(k)` |
| `pm.request.url.query.get(k)` | `qc.getParam(k)` |
| `pm.response.json(...)` | `response.json(...)` |
| `pm.response.text(...)` | `response.text(...)` |
| `pm.response.headers`, `res.headers` | `response.headers` |
| `pm.response.status`/`.code`, `res.status` | `response.status` |
| `res.body` | `response.json()` |

`.expect()` chains (`pm.expect(EXPR).to.CHAIN(...)` / bare `expect(EXPR).to.CHAIN(...)`) are pattern-matched by chain ending — `equal`, `eql`, `be.true`, `be.false`, `exist`, `include`, `match`, each with an optional `.not.` — and rewritten to `qc.expect(<condition>, "<original line>")`. Anything outside these two tables (`pm.sendRequest`, `pm.cookies`, `pm.iterationData`, `bru.runRequest`, an unrecognized `.expect()` chain) is left as raw, unconverted text and reported in the import warnings list — it will throw a `ReferenceError` at run time under qaclan's `qc`-only sandbox (no `pm`/`bru`/`expect` globals are bound), same as it would today, but the import UI now says why instead of silently producing a broken script.

**Export — reverse rewrite** (`qc_script_to_foreign`, `target: "postman" | "bruno"`): reverses the table above (`qc.set` → `pm.environment.set`/`bru.setVar`, `qc.test` → `pm.test`/bare `test`, `qc.setHeader`/`qc.setParam` → Postman's object-literal call shape `pm.request.headers.add({key,value})`/`req.setHeader` for Bruno, `response.*` → `pm.response.*`/`res.*`). `qc.expect(condition, message)` has no recoverable original chain (it was collapsed to a boolean at import time), so export regenerates a generic, always-valid equivalent: a named `pm.test(message, () => { if (!(condition)) throw new Error(message); })` when the `qc.expect(...)` call is the entire statement (preserves "this is a distinct recorded result" semantics), or an in-place `if (!(condition)) throw new Error(message);` when it's already nested inside another call's block (e.g. inside a `qc.test(...)` callback) — avoids double-wrapping a nested check in a redundant second named test. Call matching uses real paren/quote-aware scanning (`_find_matching_paren`/`_split_top_level_args` in `script_rewrite.py`), not a greedy regex, specifically so nested same-line calls don't get mis-split.

**Python** `pre_script`/`post_script` (`pre_lang`/`post_lang == "python"`) have no foreign-script equivalent in either direction — Postman/Bruno only support JS. Import never produces Python scripts from foreign input (both parsers hardcode `pre_lang`/`post_lang: "js"`); export omits Python scripts entirely rather than attempting a JS translation, and reports it as an export warning.

---

## What writes to `state.json` / how downstream steps read it

Any `qc.set("key", value)` call (script or extractor) lands in `qaclan_vars` inside the shared run state. Downstream:
- Other API requests read it via `{{key}}` in URL/headers/params/body.
- Playwright scripts read it via `os.environ["QACLAN_STATE_key"]`.

---

## Variable secrecy

Both environment variables (`env_vars.is_secret`) and collection variables (`collection_vars.is_secret`) support secret storage: Fernet-encrypted at rest (`cli/crypto.py`, key at `~/.qaclan/secret.key`), masked as `••••••••` in list/suggestion responses, and decrypted only when actually needed — at request-resolution time (`resolve_vars`, fed by `env_loader.load_env_vars` for environment vars and `CollectionVarsRepo.as_seed_dict` for collection vars) or via an explicit reveal endpoint (`GET /api/envs/<env_name>/vars/<key>/reveal`, `GET /api/collections/<col_id>/vars/<key>/reveal`), both responding with `Cache-Control: no-store`.

**Export caveat:** exporting a collection to Postman JSON or Bruno `.bru` writes secret collection vars as **decrypted plaintext** (matching the fidelity-first behavior of the rest of collection export). Treat an exported file containing secret vars with the same care as a `.env` file — avoid committing it to git or pasting it into chat.

---

## Known gaps (accurate as of this writing — update if closed)

- No `pm.sendRequest()` equivalent — scripts can't issue additional HTTP calls (nothing blocks it technically, but no helper is provided). Non-trivial to add: would need `resolve_vars`/`_apply_auth` reachable from inside the subprocess, or an IPC round-trip back to the parent process, which breaks the current one-shot write-file-and-exit sandbox model.
- No 4-tier variable scoping (global/collection/environment/local) — one flat `qaclan_vars` bucket plus the active environment's `env_vars`. Likely intentional given the local-first/single-active-environment model rather than a bug. Both tiers support secret values (`is_secret`) — see "Variable secrecy" above.
- `response.text()` exported to Bruno becomes a `res.body`-based ternary (no direct Bruno equivalent — Bruno auto-parses JSON, no separate raw-text accessor). If that exported `.bru` file is later re-imported, the import table's `res.body` → `response.json()` mapping rewrites the ternary's `res.body` references too, so the round-tripped script calls `response.json()` instead of `response.text()` — functionally near-identical when the body actually is JSON, but `json()` throws where `text()` wouldn't on a non-JSON body. Only surfaces on export-then-reimport of qaclan's own output, not on a first import from a real Postman/Bruno collection.
